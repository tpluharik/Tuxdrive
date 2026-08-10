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


def safe_streaming_overlap(first: "SyncJob", second: "SyncJob") -> bool:
    if not paths_overlap(first.local, second.local) or first.local == second.local:
        return False
    if first.mode is SyncMode.VIRTUAL_DRIVE and second.mode is not SyncMode.VIRTUAL_DRIVE:
        return second.local in first.local.parents
    if second.mode is SyncMode.VIRTUAL_DRIVE and first.mode is not SyncMode.VIRTUAL_DRIVE:
        return first.local in second.local.parents
    return False


class Provider(str, Enum):
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"
    DROPBOX = "dropbox"
    BOX = "box"
    PCLOUD = "pcloud"
    MEGA = "mega"
    PROTON_DRIVE = "proton_drive"
    NEXTCLOUD = "nextcloud"
    PEER = "peer"
    VAULT = "vault"

    @property
    def label(self) -> str:
        return {
            self.GOOGLE_DRIVE: "Google Drive",
            self.ONEDRIVE: "Microsoft OneDrive",
            self.DROPBOX: "Dropbox",
            self.BOX: "Box",
            self.PCLOUD: "pCloud",
            self.MEGA: "MEGA",
            self.PROTON_DRIVE: "Proton Drive",
            self.NEXTCLOUD: "Nextcloud",
            self.PEER: "Peer-to-peer",
            self.VAULT: "Encrypted vault",
        }[self]

    @property
    def rclone_type(self) -> str:
        return {
            self.GOOGLE_DRIVE: "drive",
            self.ONEDRIVE: "onedrive",
            self.DROPBOX: "dropbox",
            self.BOX: "box",
            self.PCLOUD: "pcloud",
            self.MEGA: "mega",
            self.PROTON_DRIVE: "protondrive",
            self.NEXTCLOUD: "webdav",
            self.PEER: "sftp",
            self.VAULT: "crypt",
        }[self]

    @property
    def icon_name(self) -> str:
        if self is self.PEER:
            return "network-workgroup-symbolic"
        if self is self.VAULT:
            return "changes-prevent-symbolic"
        return f"tuxdrive-{self.value.replace('_', '-')}"

    @property
    def key_prefix(self) -> str:
        return {
            self.GOOGLE_DRIVE: "google",
            self.ONEDRIVE: "onedrive",
            self.DROPBOX: "dropbox",
            self.BOX: "box",
            self.PCLOUD: "pcloud",
            self.MEGA: "mega",
            self.PROTON_DRIVE: "proton",
            self.NEXTCLOUD: "nextcloud",
            self.PEER: "peer",
            self.VAULT: "vault",
        }[self]

    @property
    def browser_oauth(self) -> bool:
        return self in {
            self.GOOGLE_DRIVE, self.ONEDRIVE, self.DROPBOX, self.BOX, self.PCLOUD,
        }

    @property
    def initial_options(self) -> tuple[str, ...]:
        if self is self.NEXTCLOUD:
            return ("vendor", "nextcloud")
        if self is self.PROTON_DRIVE:
            # Proton's backend warns that its metadata cache can become stale
            # when another client changes a mounted drive.
            return ("enable_caching", "false")
        return ()

    @property
    def credential_fields(self) -> tuple[tuple[str, str, bool, bool], ...]:
        """(config key, UI label, secret, required) for non-OAuth providers."""
        return {
            self.MEGA: (
                ("user", "MEGA email", False, True),
                ("pass", "MEGA password", True, True),
            ),
            self.PROTON_DRIVE: (
                ("username", "Proton account email", False, True),
                ("password", "Proton password", True, True),
                ("otp_secret_key", "OTP secret key (optional)", True, False),
                ("mailbox_password", "Mailbox password (two-password accounts)", True, False),
            ),
            self.NEXTCLOUD: (
                ("url", "Nextcloud WebDAV URL", False, True),
                ("user", "Nextcloud username", False, True),
                ("pass", "Nextcloud app password", True, True),
            ),
        }.get(self, ())

    @property
    def home_url(self) -> str:
        return {
            self.GOOGLE_DRIVE: "https://drive.google.com/drive/my-drive",
            self.ONEDRIVE: "https://onedrive.live.com/",
            self.DROPBOX: "https://www.dropbox.com/home",
            self.BOX: "https://app.box.com/folder/0",
            self.PCLOUD: "https://my.pcloud.com/",
            self.MEGA: "https://mega.nz/fm",
            self.PROTON_DRIVE: "https://drive.proton.me/",
            self.NEXTCLOUD: "",
            self.PEER: "",
            self.VAULT: "",
        }[self]


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
    peer_host: str = ""
    peer_port: int = 2022
    peer_host_key: str = ""
    vault_base_remote: str = ""
    vault_base_path: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Account":
        return cls(
            remote=value["remote"],
            provider=Provider(value["provider"]),
            display_name=value.get("display_name", value["remote"]),
            created_at=value.get("created_at", datetime.now(timezone.utc).isoformat()),
            peer_host=value.get("peer_host", ""),
            peer_port=int(value.get("peer_port", 2022)),
            peer_host_key=value.get("peer_host_key", ""),
            vault_base_remote=value.get("vault_base_remote", ""),
            vault_base_path=value.get("vault_base_path", ""),
        )


@dataclass(slots=True)
class AuthorizedPeer:
    name: str
    public_key: str
    enabled: bool = True
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AuthorizedPeer":
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in value.items() if key in allowed})


@dataclass(slots=True)
class PeerShare:
    name: str
    local_path: str
    advertised_host: str
    port: int = 2022
    allowed_peer_key: str = ""
    id: str = field(default_factory=lambda: uuid4().hex)
    enabled: bool = True
    last_status: str = "Not started"
    authorized_peers: list[AuthorizedPeer] = field(default_factory=list)
    lan_discovery: bool = True
    lease_minutes: int = 10
    nat_traversal: bool = True
    relay_host: str = ""
    relay_user: str = ""
    relay_ssh_port: int = 22
    relay_public_port: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PeerShare":
        data = dict(value)
        peers = [AuthorizedPeer.from_dict(item) for item in data.get("authorized_peers", [])]
        legacy = data.get("allowed_peer_key", "")
        if legacy and not peers:
            peers = [AuthorizedPeer("Legacy peer", legacy)]
        data["authorized_peers"] = peers
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in data.items() if key in allowed})

    @property
    def active_peer_keys(self) -> list[str]:
        keys = [item.public_key for item in self.authorized_peers if item.enabled]
        if self.allowed_peer_key and self.allowed_peer_key not in keys:
            keys.append(self.allowed_peer_key)
        return keys


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
    version_history: bool = True
    version_retention_days: int = 30
    ransomware_protection: bool = True
    mass_change_limit: int = 200
    mass_change_percent: int = 25
    peer_leases: bool = False
    peer_lease_minutes: int = 10
    block_delta_transfer: bool = True
    peer_delta: bool = False
    offline_paths: list[str] = field(default_factory=list)
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
    nautilus_integration: bool = True
    network_policy: str = "maximum"
    allow_metered_networks: bool = True
    pause_below_battery_percent: int = 0
    schedule_start: str = ""
    schedule_end: str = ""
    config_version: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AppSettings":
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in value.items() if key in allowed})


@dataclass(slots=True)
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    jobs: list[SyncJob] = field(default_factory=list)
    peer_shares: list[PeerShare] = field(default_factory=list)
    settings: AppSettings = field(default_factory=AppSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AppConfig":
        return cls(
            accounts=[Account.from_dict(item) for item in value.get("accounts", [])],
            jobs=[SyncJob.from_dict(item) for item in value.get("jobs", [])],
            peer_shares=[PeerShare.from_dict(item) for item in value.get("peer_shares", [])],
            settings=AppSettings.from_dict(value.get("settings", {})),
        )
