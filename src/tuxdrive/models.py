from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def paths_overlap(first: str | Path, second: str | Path) -> bool:
    left = Path(first).expanduser().resolve(strict=False)
    right = Path(second).expanduser().resolve(strict=False)
    return left == right or left in right.parents or right in left.parents


class Provider(str, Enum):
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"

    @property
    def label(self) -> str:
        return "Google Drive" if self is Provider.GOOGLE_DRIVE else "Microsoft OneDrive"

    @property
    def rclone_type(self) -> str:
        return "drive" if self is Provider.GOOGLE_DRIVE else "onedrive"


class SyncMode(str, Enum):
    TWO_WAY = "two_way"
    DOWNLOAD_ONLY = "download_only"
    UPLOAD_ONLY = "upload_only"
    VIRTUAL_DRIVE = "virtual_drive"

    @property
    def label(self) -> str:
        return {
            self.TWO_WAY: "Two-way sync",
            self.DOWNLOAD_ONLY: "Download mirror",
            self.UPLOAD_ONLY: "Upload mirror",
            self.VIRTUAL_DRIVE: "Streaming drive (files on demand)",
        }[self]


class ConflictPolicy(str, Enum):
    KEEP_BOTH = "keep_both"
    NEWER_WINS = "newer_wins"
    LOCAL_WINS = "local_wins"
    CLOUD_WINS = "cloud_wins"


@dataclass(slots=True)
class Account:
    remote: str
    provider: Provider
    display_name: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Account":
        return cls(
            remote=value["remote"],
            provider=Provider(value["provider"]),
            display_name=value.get("display_name", value["remote"]),
            created_at=value.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass(slots=True)
class SyncJob:
    account_remote: str
    local_path: str
    remote_path: str = ""
    remote_scope: str = ""
    cloud_location_name: str = ""
    mode: SyncMode = SyncMode.TWO_WAY
    name: str = "Cloud files"
    enabled: bool = True
    interval_minutes: int = 5
    conflict_policy: ConflictPolicy = ConflictPolicy.KEEP_BOTH
    exclude_patterns: list[str] = field(default_factory=lambda: [".Trash-*/**", "*.part", "~$*"])
    max_delete: int = 100
    bandwidth_limit: str = ""
    acknowledge_google_abuse: bool = False
    realtime_sync: bool = True
    id: str = field(default_factory=lambda: uuid4().hex)
    initialized: bool = False
    last_run: str | None = None
    last_status: str = "Not synchronized yet"
    last_error: str = ""

    @property
    def remote_spec(self) -> str:
        remote_path = self.remote_path.strip("/")
        remote = self.remote_scope or self.account_remote
        return f"{remote}:{remote_path}" if remote_path else f"{remote}:"

    @property
    def local(self) -> Path:
        return Path(self.local_path).expanduser()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SyncJob":
        data = dict(value)
        data["mode"] = SyncMode(data.get("mode", SyncMode.TWO_WAY.value))
        data["conflict_policy"] = ConflictPolicy(
            data.get("conflict_policy", ConflictPolicy.KEEP_BOTH.value)
        )
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in data.items() if key in allowed})


@dataclass(slots=True)
class AppSettings:
    launch_at_login: bool = True
    notifications: bool = True
    start_minimized: bool = False
    rclone_path: str = "rclone"
    config_version: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AppSettings":
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in value.items() if key in allowed})


@dataclass(slots=True)
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    jobs: list[SyncJob] = field(default_factory=list)
    settings: AppSettings = field(default_factory=AppSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AppConfig":
        return cls(
            accounts=[Account.from_dict(item) for item in value.get("accounts", [])],
            jobs=[SyncJob.from_dict(item) for item in value.get("jobs", [])],
            settings=AppSettings.from_dict(value.get("settings", {})),
        )
