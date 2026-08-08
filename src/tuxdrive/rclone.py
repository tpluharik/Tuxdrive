from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Provider


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


class RcloneClient:
    """Small, auditable interface to rclone.

    OAuth tokens stay in rclone's mode-0600 configuration. TuxDrive never
    writes tokens to its own JSON configuration and never emits config dumps
    into logs.
    """

    def __init__(self, executable: str = "rclone") -> None:
        self.executable = executable

    def available(self) -> bool:
        return bool(shutil.which(self.executable))

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
        for name, values in raw.items():
            backend = values.get("type") if isinstance(values, dict) else None
            if backend == "drive":
                accounts[name] = Provider.GOOGLE_DRIVE
            elif backend == "onedrive":
                accounts[name] = Provider.ONEDRIVE
        return accounts

    def begin_oauth(
        self,
        remote: str,
        provider: Provider,
        client_id: str = "",
        client_secret: str = "",
    ) -> ConfigResult:
        self._validate_remote_name(remote)
        args = ["config", "create", remote, provider.rclone_type]
        if client_id:
            args.extend(["client_id", client_id])
        if client_secret:
            args.extend(["client_secret", client_secret])
        args.append("--non-interactive")
        return self._configuration_step(args)

    def continue_oauth(
        self,
        remote: str,
        state: str,
        answer: str,
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
            ]
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

    def _configuration_step(self, args: list[str]) -> ConfigResult:
        result = self._run(args, timeout=600)
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

    def _run(
        self,
        args: Iterable[str],
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if not self.available():
            raise RcloneError("rclone is not installed or is not on PATH")
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
