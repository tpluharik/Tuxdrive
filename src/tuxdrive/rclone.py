from __future__ import annotations

import json
import os
import signal
import shutil
import socket
import subprocess
import threading
from urllib.parse import quote
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

    def copy_to(self, source: str | Path, destination: str | Path) -> None:
        """Copy one object without exposing its contents to logs or stdout."""
        self._run(["copyto", str(source), str(destination)])

    def object_exists(self, spec: str) -> bool:
        try:
            self._run(["lsjson", "--stat", spec])
            return True
        except RcloneError:
            return False

    def config_file(self) -> Path:
        result = self._run(["config", "file"])
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if lines:
            candidate = Path(lines[-1]).expanduser()
            if candidate.is_file():
                return candidate
        fallback = Path.home() / ".config" / "rclone" / "rclone.conf"
        if fallback.is_file():
            return fallback
        raise RcloneError("Could not locate rclone's private configuration file")

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
            if provider not in {Provider.NEXTCLOUD, Provider.PEER}
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
        credentials: dict[str, str] | None = None,
    ) -> ConfigResult:
        self._validate_remote_name(remote)
        args = ["config", "create", remote, provider.rclone_type]
        args.extend(provider.initial_options)
        if client_id:
            args.extend(["client_id", client_id])
        if client_secret:
            args.extend(["client_secret", client_secret])
        secret_keys = {
            key for key, _label, secret, _required in provider.credential_fields if secret
        }
        for key, value in (credentials or {}).items():
            if not value:
                continue
            args.extend([key, self._obscure(value) if key in secret_keys else value])
        args.append("--non-interactive")
        return self._configuration_step(args, session_id)

    def validate_remote(self, remote: str) -> None:
        self._validate_remote_name(remote)
        self._run(["lsf", f"{remote}:", "--dirs-only", "--max-depth", "1"])

    def create_crypt_remote(
        self,
        remote: str,
        base_spec: str,
        password: str,
        password2: str = "",
        filename_encryption: str = "standard",
    ) -> None:
        """Create a crypt remote without ever placing cleartext secrets in config."""
        self._validate_remote_name(remote)
        if not base_spec or ":" not in base_spec:
            raise RcloneError("Choose a configured storage account and a dedicated vault folder")
        if not password:
            raise RcloneError("A vault password is required")
        if filename_encryption not in {"standard", "obfuscate", "off"}:
            raise RcloneError("Unsupported filename encryption mode")
        args = [
            "config", "create", remote, "crypt",
            "remote", base_spec,
            "filename_encryption", filename_encryption,
            "directory_name_encryption", "true",
            "password", self._obscure(password),
        ]
        if password2:
            args.extend(["password2", self._obscure(password2)])
        args.append("--non-interactive")
        self._run(args)
        self.validate_remote(remote)

    def update_credentials(
        self, remote: str, provider: Provider, credentials: dict[str, str]
    ) -> None:
        self._validate_remote_name(remote)
        secret_keys = {
            key for key, _label, secret, _required in provider.credential_fields if secret
        }
        # A current Proton 2FA code is sensitive but rclone expects it as a
        # plain config value rather than an obscured password.
        args = ["config", "update", remote]
        for key, value in credentials.items():
            if value:
                args.extend([key, self._obscure(value) if key in secret_keys else value])
        args.append("--non-interactive")
        self._run(args)

    @staticmethod
    def requires_proton_2fa(error: Exception | str) -> bool:
        detail = str(error).lower()
        return any(
            marker in detail
            for marker in (
                "2fa enabled",
                "2fa code",
                "two-factor",
                "two factor",
                "totp",
            )
        )

    def _obscure(self, value: str) -> str:
        if not self.available():
            self.ensure_available()
        result = subprocess.run(
            [self.executable, "obscure", "-"],
            input=value,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode or not result.stdout.strip():
            raise RcloneError("Could not protect the provider password before configuration")
        return result.stdout.strip()

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

    def online_url(self, remote_spec: str, provider: Provider) -> tuple[str, bool]:
        """Return a non-sharing provider URL and whether it targets the exact item."""
        remote_name, _, raw_path = remote_spec.partition(":")
        remote_path = raw_path.strip("/")
        if provider is Provider.DROPBOX:
            suffix = f"/{quote(remote_path, safe='/')}" if remote_path else ""
            return f"https://www.dropbox.com/home{suffix}", True

        metadata: dict[str, Any] = {}
        if remote_path and provider in {Provider.GOOGLE_DRIVE, Provider.ONEDRIVE, Provider.BOX}:
            try:
                result = self._run(["lsjson", remote_spec, "--stat", "--no-mimetype", "--no-modtime"])
                metadata = json.loads(result.stdout or "{}")
            except (RcloneError, json.JSONDecodeError):
                metadata = {}
        # Some Google Drive/rclone combinations omit ID from an lsjson --stat
        # response even though normal directory listings contain it. Resolve
        # the selected item from its direct parent before falling back to the
        # provider home page. The scoped remote name is preserved, so this also
        # works for My Drive, Shared with me, and Shared Drives.
        if provider is Provider.GOOGLE_DRIVE and remote_path and not metadata.get("ID"):
            parent, _, child = remote_path.rpartition("/")
            parent_spec = f"{remote_name}:{parent}" if parent else f"{remote_name}:"
            try:
                result = self._run([
                    "lsjson", parent_spec, "--max-depth", "1",
                    "--no-mimetype", "--no-modtime",
                ])
                entries = json.loads(result.stdout or "[]")
                if isinstance(entries, list):
                    metadata = next(
                        (
                            item for item in entries
                            if isinstance(item, dict)
                            and str(item.get("Name") or item.get("Path") or "").strip("/") == child
                            and item.get("ID")
                        ),
                        {},
                    )
            except (RcloneError, json.JSONDecodeError):
                metadata = {}
        item_id = str(metadata.get("ID", "")).strip()
        is_dir = bool(metadata.get("IsDir", True))
        if item_id and provider is Provider.GOOGLE_DRIVE:
            return (
                f"https://drive.google.com/drive/folders/{quote(item_id, safe='')}"
                if is_dir else f"https://drive.google.com/open?id={quote(item_id, safe='')}",
                True,
            )
        if item_id and provider is Provider.BOX and is_dir:
            return f"https://app.box.com/folder/{quote(item_id, safe='')}", True
        if item_id and provider is Provider.ONEDRIVE:
            return f"https://onedrive.live.com/?id={quote(item_id, safe='!')}", True
        return provider.home_url, False

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
