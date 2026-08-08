from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import AppConfig


def config_home() -> Path:
    root = os.environ.get("XDG_CONFIG_HOME")
    return Path(root) if root else Path.home() / ".config"


def cache_home() -> Path:
    root = os.environ.get("XDG_CACHE_HOME")
    return Path(root) if root else Path.home() / ".cache"


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_home() / "tuxdrive" / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return AppConfig.from_dict(json.load(handle))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            backup = self.path.with_suffix(".json.invalid")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            raise RuntimeError(f"Invalid TuxDrive configuration; moved to {backup}") from exc

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(
            prefix="config-", suffix=".json", dir=self.path.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(config.to_dict(), handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
