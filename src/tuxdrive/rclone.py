from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Provider
from .bootstrap import install_rclone, resolve_rclone


class RcloneError(RuntimeError):
    pass


@dataclass(slots=True)
class ConfigQuestion:
    state: str
    name: str
    help: str
    default: Any
    examples: list[dict[str, Any]]
    required: bool
    secret: bool
    exclusive: bool
    error: str = ""


@dataclass(slots=True)
class ConfigResult:
    complete: bool
    question: ConfigQuestion | None = None


@dataclass(slots=True)
class DriveLocation:
    key: str
    name: str
    scoped_remote: str


class RcloneClient:
    """Small, auditable interface to rclone.

    OAuth tokens stay in rclone's mode-0600 configuration. TuxDrive never
    writes tokens to its own JSON configuration and never emits config dumps
    into logs.
    """

    def __init__(self, executable: str = "rclone") -> None:
        self.executable = executable
        self._oauth_guard = threading.Lock()
        self._oauth_process: subprocess.Popen[str] | None = None
        self._oauth_session: str | None = None

    def available(self) -> bool:
        resolved = resolve_rclone(self.executable)
        if resolved:
            self.executable = resolved
            return True
        return False

    def ensure_available(self) -> str:
        if self.available():
            return self.executable
        self.executable = install_rclone()
        return self.executable

    def version(self) -> str:
        result = self._run(["version"])
        return result.stdout.splitlines()[0] if result.stdout else "rclone"

    def list_remotes(self) -> list[str]:
        result = self._run(["listremotes"])
        return [line.rstrip(":") for line in result.stdout.splitlines() if line.strip()]

    def discover_accounts(self) -> dict[str, Provider]:
        # The dump is parsed only in memory and is never returned or logged.
        result = self._run(["config", "dump"])
        try:
            raw = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RcloneError("rclone returned an invalid configuration") from exc
        accounts: dict[str, Provider] = {}
        backend_map = {
            provider.rclone_type: provider
            for provider in Provider
            if provider is not Provider.NEXTCLOUD
        }
        for name, values in raw.items():
            backend = values.get("type") if isinstance(values, dict) else None
            if backend in backend_map:
                accounts[name] = backend_map[backend]
            elif backend == "webdav" and isinstance(values, dict) and values.get("vendor") == "nextcloud":
                accounts[name] = Provider.NEXTCLOUD
        return accounts

    def begin_oauth(
        self,
        remote: str,
        provider: Provider,
        client_id: str = "",
        client_secret: str = "",
        session_id: str = "",
    ) -> ConfigResult:
        self._validate_remote_name(remote)
        args = ["config", "create", remote, provider.rclone_type]
        args.extend(provider.initial_options)
        if client_id:
            args.extend(["client_id", client_id])
        if client_secret:
            args.extend(["client_secret", client_secret])
        args.append("--non-interactive")
        return self._configuration_step(args, session_id)

    def continue_oauth(
        self,
        remote: str,
        state: str,
        answer: str,
        session_id: str = "",
    ) -> ConfigResult:
        self._validate_remote_name(remote)
        return self._configuration_step(
            [
                "config",
                "update",
                remote,
                "--continue",
                "--state",
                state,
                "--result",
                answer,
                "--non-interactive",
            ],
            session_id,
        )

    def reconnect(self, remote: str) -> subprocess.CompletedProcess[str]:
        self._validate_remote_name(remote)
        return self._run(["config", "reconnect", f"{remote}:"])

    def delete_remote(self, remote: str) -> None:
        self._validate_remote_name(remote)
        self._run(["config", "delete", remote])

    def list_directories(self, remote: str, remote_path: str = "") -> list[str]:
        self._validate_remote_name(remote)
        spec = f"{remote}:{remote_path.strip('/')}"
        result = self._run(["lsf", spec, "--dirs-only", "--max-depth", "1"])
        return sorted(line.rstrip("/") for line in result.stdout.splitlines() if line.strip())

    def google_drive_locations(self, remote: str) -> list[DriveLocation]:
        self._validate_remote_name(remote)
        locations = [
            DriveLocation(
                "my_drive",
                "My Drive",
                google_scoped_remote(remote, "my_drive"),
            ),
            DriveLocation(
                "shared_with_me",
                "Shared with me",
                google_scoped_remote(remote, "shared_with_me"),
            ),
            DriveLocation(
                "configured",
                "Previously configured root",
                remote,
            ),
        ]
        result = self._run(["backend", "drives", f"{remote}:"])
        try:
            shared_drives = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RcloneError("Google returned an invalid Shared Drive list") from exc
        for item in shared_drives:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            drive_id = str(item["id"])
            name = str(item.get("name") or drive_id)
            locations.append(
                DriveLocation(
                    f"shared_drive:{drive_id}",
                    f"Shared Drive · {name}",
                    google_scoped_remote(remote, "shared_drive", drive_id),
                )
            )
        return locations

    def public_link(self, remote_spec: str) -> str:
        result = self._run(["link", remote_spec])
        return result.stdout.strip()

    def about(self, remote: str) -> dict[str, Any]:
        self._validate_remote_name(remote)
        result = self._run(["about", f"{remote}:", "--json"])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}

    def _configuration_step(self, args: list[str], session_id: str = "") -> ConfigResult:
        result = self._run_oauth(args, session_id, timeout=600)
        output = result.stdout.strip()
        if not output:
            return ConfigResult(complete=True)
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            # Some successful backend configurations print informational text.
            return ConfigResult(complete=True)
        state = value.get("State", "")
        option = value.get("Option")
        if not state or not option:
            return ConfigResult(complete=True)
        return ConfigResult(
            complete=False,
            question=ConfigQuestion(
                state=state,
                name=option.get("Name", "option"),
                help=option.get("Help", ""),
                default=option.get("Default", ""),
                examples=option.get("Examples") or [],
                required=bool(option.get("Required")),
                secret=bool(option.get("IsPassword")),
                exclusive=bool(option.get("Exclusive")),
                error=value.get("Error", ""),
            ),
        )

    def _run_oauth(
        self, args: list[str], session_id: str, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        if not self.available():
            self.ensure_available()
        if "--continue" in args and self._callback_port_busy():
            raise RcloneError(
                "The OAuth callback port (127.0.0.1:53682) is already in use. "
                "Close the earlier TuxDrive/rclone authorization attempt, then try again."
            )
        environment = os.environ.copy()
        environment.setdefault("LC_ALL", "C.UTF-8")
        with self._oauth_guard:
            if self._oauth_process is not None and self._oauth_process.poll() is None:
                raise RcloneError("Another cloud authorization is already in progress.")
            process = subprocess.Popen(
                [self.executable, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
                start_new_session=True,
            )
            self._oauth_process = process
            self._oauth_session = session_id
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self.cancel_oauth(session_id)
            raise RcloneError("Authorization timed out. Please try again.") from exc
        finally:
            with self._oauth_guard:
                if self._oauth_process is process:
                    self._oauth_process = None
                    self._oauth_session = None
        if process.returncode:
            raise RcloneError(self._friendly_oauth_error(stderr or stdout))
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def cancel_oauth(self, session_id: str) -> None:
        """Stop only the authorization process owned by the requesting wizard."""
        with self._oauth_guard:
            process = self._oauth_process
            if process is None or self._oauth_session != session_id or process.poll() is not None:
                return
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def _callback_port_busy() -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.15)
            return probe.connect_ex(("127.0.0.1", 53682)) == 0

    @staticmethod
    def _friendly_oauth_error(message: str) -> str:
        text = message.strip()
        if "address already in use" in text.lower():
            return (
                "The OAuth callback port (127.0.0.1:53682) is already in use. "
                "Close the earlier TuxDrive/rclone authorization attempt, then try again."
            )
        meaningful = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(meaningful):
            if line.lower().startswith(("fatal error:", "error:")):
                return line[:500]
        return (meaningful[0] if meaningful else "Cloud authorization failed")[:500]

    def _run(
        self,
        args: Iterable[str],
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if not self.available():
            try:
                self.ensure_available()
            except Exception as exc:
                raise RcloneError(str(exc)) from exc
        environment = os.environ.copy()
        environment.setdefault("LC_ALL", "C.UTF-8")
        try:
            return subprocess.run(
                [self.executable, *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise RcloneError("The cloud operation timed out") from exc
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or "rclone operation failed").strip()
            raise RcloneError(message) from exc

    @staticmethod
    def _validate_remote_name(remote: str) -> None:
        if not remote or any(character in remote for character in ":/\\\n\r\t"):
            raise ValueError("Remote names cannot contain spaces, slashes, colons, or control characters")
        if " " in remote:
            raise ValueError("Remote names cannot contain spaces")


def rclone_config_path() -> Path:
    configured = os.environ.get("RCLONE_CONFIG")
    if configured:
        return Path(configured)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "rclone" / "rclone.conf"


def google_scoped_remote(remote: str, kind: str, drive_id: str = "") -> str:
    """Build an rclone connection string without copying OAuth credentials."""
    if kind == "my_drive":
        return f"{remote},team_drive=,root_folder_id=root,shared_with_me=false"
    if kind == "shared_with_me":
        return f"{remote},team_drive=,root_folder_id=root,shared_with_me=true"
    if kind == "shared_drive" and drive_id:
        return f"{remote},team_drive={drive_id},root_folder_id=,shared_with_me=false"
    return remote
