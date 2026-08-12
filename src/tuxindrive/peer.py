from __future__ import annotations

import json
import base64
import hashlib
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
import shlex
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .bootstrap import install_rclone, resolve_rclone
from .config import cache_root, config_root
from .audit import AuditTimeline
from .models import AuthorizedPeer, OneTimeDrop, PeerRole, PeerShare, PeerTransportPolicy, SyncJob
from .tor import ONION_V3, TorError, TorServiceManager, enforce_transport_policy
from .security import confined_path, confined_parent, ensure_private_directory, prepare_private_file, verify_signed_json


class PeerError(RuntimeError):
    pass


PUBLIC_KEY = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/]+={0,3}(?: .*)?$"
)


def _endpoint_label(public_key: str) -> str:
    return hashlib.sha256(normalize_public_key(public_key).encode("utf-8")).hexdigest()[:24]


@dataclass(slots=True)
class PeerInvitation:
    name: str
    host: str
    port: int
    host_key: str
    share_id: str = ""
    lease_minutes: int = 10
    relay_host: str = ""
    relay_port: int = 0
    role: PeerRole = PeerRole.READ_WRITE
    remote_path: str = ""
    one_time_drop_id: str = ""
    expires_at: str = ""
    transport: str = "direct"
    onion_address: str = ""
    onion_client_auth: str = ""
    allowed_transports: tuple[str, ...] = ()

    def encode(self) -> str:
        allowed_transports = self.allowed_transports or (self.transport,)
        return json.dumps(
            {
                "tuxindrive_peer": 5,
                "name": self.name,
                "host": self.host,
                "port": self.port,
                "host_key": self.host_key,
                "share_id": self.share_id,
                "lease_minutes": self.lease_minutes,
                "relay_host": self.relay_host,
                "relay_port": self.relay_port,
                "role": self.role.value,
                "remote_path": self.remote_path,
                "one_time_drop_id": self.one_time_drop_id,
                "expires_at": self.expires_at,
                "transport": self.transport,
                "onion_address": self.onion_address,
                "onion_client_auth": self.onion_client_auth,
                "allowed_transports": list(allowed_transports),
            },
            indent=2,
        )

    @classmethod
    def decode(cls, value: str) -> "PeerInvitation":
        try:
            data = json.loads(value)
            schema = data.get("tuxindrive_peer", data.get("tuxdrive_peer"))
            if schema not in (1, 2, 3, 4, 5):
                raise ValueError
            invitation = cls(
                name=str(data.get("name") or "Peer folder"),
                host=validate_host(str(data["host"])),
                port=validate_port(int(data["port"])),
                host_key=normalize_public_key(str(data["host_key"])),
                share_id=str(data.get("share_id") or ""),
                lease_minutes=max(1, min(1440, int(data.get("lease_minutes", 10)))),
                relay_host=validate_host(str(data["relay_host"])) if data.get("relay_host") else "",
                relay_port=validate_port(int(data["relay_port"])) if data.get("relay_port") else 0,
                role=PeerRole(data.get("role", PeerRole.READ_WRITE.value)),
                remote_path=str(data.get("remote_path") or "").strip("/"),
                one_time_drop_id=str(data.get("one_time_drop_id") or ""),
                expires_at=str(data.get("expires_at") or ""),
                transport=str(data.get("transport") or "direct"),
                onion_address=str(data.get("onion_address") or "").lower(),
                onion_client_auth=str(data.get("onion_client_auth") or ""),
                allowed_transports=tuple(data.get("allowed_transports") or (str(data.get("transport") or "direct"),)),
            )
            if invitation.transport not in {"direct", "relay", "tor"}:
                raise ValueError
            if not invitation.allowed_transports or any(item not in {"direct", "relay", "tor"} for item in invitation.allowed_transports):
                raise ValueError
            if invitation.transport not in invitation.allowed_transports:
                raise ValueError
            if invitation.transport == "tor" and not ONION_V3.fullmatch(invitation.onion_address):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PeerError("The peer invitation is incomplete or invalid") from exc
        return invitation

    def assert_usable(self) -> None:
        if self.expires_at:
            try:
                if datetime.fromisoformat(self.expires_at) <= datetime.now(timezone.utc):
                    raise PeerError("This one-time file-drop invitation has expired")
            except (TypeError, ValueError) as exc:
                raise PeerError("The invitation expiry is invalid") from exc


def validate_host(value: str) -> str:
    host = value.strip()
    if not host or len(host) > 253 or any(character.isspace() for character in host):
        raise PeerError("Enter the current IP address or DNS name of the sharing machine")
    if any(character in host for character in "/:@"):
        raise PeerError("The peer address must not include a scheme, port, or path")
    return host


def validate_port(value: int) -> int:
    if not 1024 <= value <= 65535:
        raise PeerError("Use an unprivileged TCP port between 1024 and 65535")
    return value


def normalize_public_key(value: str) -> str:
    line = " ".join(value.strip().split())
    if "\n" in value.strip() or not PUBLIC_KEY.fullmatch(line):
        raise PeerError("Paste one OpenSSH public key (ssh-ed25519, RSA, or ECDSA)")
    key_type, encoded, *_comment = line.split(" ")
    return f"{key_type} {encoded}"


def key_fingerprint(value: str) -> str:
    normalized = normalize_public_key(value)
    encoded = normalized.split()[1]
    digest = hashlib.sha256(base64.b64decode(encoded + "===")).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


@dataclass(frozen=True, slots=True)
class DiscoveredPeer:
    name: str
    host: str
    port: int
    host_key: str
    share_id: str
    lease_minutes: int = 10

    @property
    def fingerprint(self) -> str:
        return key_fingerprint(self.host_key)

    def invitation(self) -> PeerInvitation:
        return PeerInvitation(self.name, self.host, self.port, self.host_key, self.share_id, self.lease_minutes)


class LanDiscovery:
    """Optional local-network announcements; fingerprints still require confirmation."""

    GROUP = "239.255.77.77"
    PORT = 47777

    def __init__(self, invitation_provider) -> None:
        self.invitation_provider = invitation_provider
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopped.clear()
        self._thread = threading.Thread(target=self._announce, daemon=True, name="peer-lan-discovery")
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def _announce(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        try:
            while not self._stopped.is_set():
                for invitation in self.invitation_provider():
                    payload = json.dumps({"tuxindrive_lan": 1, **json.loads(invitation.encode())}).encode("utf-8")
                    try:
                        sock.sendto(payload, (self.GROUP, self.PORT))
                    except OSError:
                        pass
                self._stopped.wait(2.0)
        finally:
            sock.close()

    @classmethod
    def discover(cls, timeout: float = 3.5) -> list[DiscoveredPeer]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", cls.PORT))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, struct.pack("4sL", socket.inet_aton(cls.GROUP), socket.INADDR_ANY))
        sock.settimeout(0.25)
        deadline = time.monotonic() + max(0.2, timeout)
        found: dict[tuple[str, int, str], DiscoveredPeer] = {}
        try:
            while time.monotonic() < deadline:
                try:
                    payload, address = sock.recvfrom(65535)
                    data = json.loads(payload.decode("utf-8"))
                    if data.get("tuxindrive_lan", data.get("tuxdrive_lan")) != 1:
                        continue
                    invitation = PeerInvitation.decode(json.dumps(data))
                    peer = DiscoveredPeer(invitation.name, address[0], invitation.port, invitation.host_key, invitation.share_id, invitation.lease_minutes)
                    found[(peer.host, peer.port, peer.share_id)] = peer
                except (OSError, UnicodeError, json.JSONDecodeError, PeerError):
                    continue
        finally:
            sock.close()
        return sorted(found.values(), key=lambda item: (item.name.lower(), item.host, item.port))


@dataclass(frozen=True, slots=True)
class FileLease:
    path: str
    owner: str
    token: str
    expires_at: str

    @property
    def expired(self) -> bool:
        try:
            return datetime.fromisoformat(self.expires_at) <= datetime.now(timezone.utc)
        except ValueError:
            return True


class PeerLeaseManager:
    """Cooperative expiring leases stored on the authenticated peer share."""

    def __init__(self, rclone_path: str = "rclone", root: Path | None = None) -> None:
        self.rclone_path = rclone_path
        self.root = root or config_root() / "peer"
        self._owner: str | None = None

    @property
    def owner(self) -> str:
        if self._owner is None:
            self._owner = self._owner_id()
        return self._owner

    def acquire(self, job: SyncJob, relative: str) -> FileLease:
        relative = self._relative(relative)
        current = self.read(job, relative)
        if current and not current.expired and current.owner != self.owner:
            raise PeerError(f"{relative} is being edited by {current.owner} until {current.expires_at}")
        lease = FileLease(relative, self.owner, uuid4().hex, (datetime.now(timezone.utc) + timedelta(minutes=max(1, job.peer_lease_minutes))).isoformat())
        self._write(job, lease)
        confirmed = self.read(job, relative)
        if not confirmed or confirmed.token != lease.token:
            raise PeerError(f"Could not acquire the edit lease for {relative}; another peer won the lease")
        return lease

    def release(self, job: SyncJob, lease: FileLease) -> None:
        current = self.read(job, lease.path)
        if not current or current.token != lease.token:
            return
        self._run([self.rclone_path, "deletefile", self._spec(job, lease.path)], allow_missing=True)

    def read(self, job: SyncJob, relative: str) -> FileLease | None:
        result = subprocess.run([self.rclone_path, "cat", self._spec(job, relative)], capture_output=True, text=True, timeout=20, check=False)
        if result.returncode:
            return None
        try:
            value = json.loads(result.stdout)
            return FileLease(str(value["path"]), str(value["owner"]), str(value["token"]), str(value["expires_at"]))
        except (KeyError, TypeError, json.JSONDecodeError):
            return None

    def foreign_leases(self, job: SyncJob) -> list[FileLease]:
        result = subprocess.run([self.rclone_path, "lsf", f"{job.account_remote}:.tuxdrive-leases", "--files-only"], capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            return []
        leases = []
        for filename in result.stdout.splitlines():
            if not filename.endswith(".json"):
                continue
            raw = subprocess.run([self.rclone_path, "cat", f"{job.account_remote}:.tuxdrive-leases/{filename}"], capture_output=True, text=True, timeout=20, check=False)
            try:
                value = json.loads(raw.stdout)
                lease = FileLease(str(value["path"]), str(value["owner"]), str(value["token"]), str(value["expires_at"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if not lease.expired and lease.owner != self.owner:
                leases.append(lease)
        return leases

    def _write(self, job: SyncJob, lease: FileLease) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as handle:
            json.dump({field: getattr(lease, field) for field in lease.__dataclass_fields__}, handle)
            temporary = Path(handle.name)
        try:
            self._run([self.rclone_path, "copyto", str(temporary), self._spec(job, lease.path)])
        finally:
            temporary.unlink(missing_ok=True)

    def _spec(self, job: SyncJob, relative: str) -> str:
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()
        return f"{job.account_remote}:.tuxdrive-leases/{digest}.json"

    def _owner_id(self) -> str:
        path = self.root / "lease-owner"
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        value = f"{socket.gethostname()}-{uuid4().hex[:8]}"
        path.write_text(value + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
        return value

    @staticmethod
    def _relative(value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise PeerError("Refused an unsafe lease path")
        return path.as_posix()

    @staticmethod
    def _run(command: list[str], allow_missing: bool = False) -> None:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode and not allow_missing:
            raise PeerError((result.stderr or result.stdout or "Peer lease operation failed").strip()[-600:])


class PeerManager:
    """Runs direct, mutually authenticated SFTP shares between TuxInDrive peers."""

    def __init__(self, rclone_path: str = "rclone", root: Path | None = None, audit: AuditTimeline | None = None) -> None:
        self.rclone_path = rclone_path
        self.root = root or config_root() / "peer"
        self._servers: dict[str, subprocess.Popen[str]] = {}
        self._shares: dict[str, PeerShare] = {}
        self._logs: dict[str, object] = {}
        self._tunnels: dict[str, subprocess.Popen[str]] = {}
        self._nat_ports: dict[str, list[int]] = {}
        self._lock = threading.RLock()
        self.audit = audit or AuditTimeline()
        self.discovery = LanDiscovery(self._discovery_invitations)
        self.tor = TorServiceManager(self.root / "tor")

    @property
    def running_shares(self) -> set[str]:
        with self._lock:
            return {
                share_id.split(":", 1)[0] for share_id, process in self._servers.items()
                if process.poll() is None
            }

    @staticmethod
    def _assign_endpoint_ports(share: PeerShare) -> None:
        used: set[int] = set()
        next_port = validate_port(int(share.port))
        endpoints = [item for item in share.authorized_peers if item.enabled]
        drops = [item for item in share.one_time_drops if item.active]
        for item in [*endpoints, *drops]:
            port = int(item.server_port or 0)
            if port < 1024 or port > 65535 or port in used:
                while next_port in used:
                    next_port += 1
                port = validate_port(next_port)
                item.server_port = port
            used.add(port)
            next_port = max(next_port, port + 1)

    @staticmethod
    def _peer_for_invitation(share: PeerShare, peer_name: str) -> AuthorizedPeer:
        peers = [item for item in share.authorized_peers if item.enabled]
        peer = next((item for item in peers if item.name == peer_name), None)
        if peer is None and len(peers) == 1:
            peer = peers[0]
        if peer is None:
            raise PeerError("Select the authorized device that will receive this invitation")
        return peer

    @staticmethod
    def _relay_port(share: PeerShare, endpoint_port: int) -> int:
        return validate_port(int(share.relay_public_port) + int(endpoint_port) - int(share.port))

    def ensure_identity(self) -> tuple[Path, Path]:
        return self._ensure_keypair(self.root / "identity_ed25519")

    def identity_public_key(self) -> str:
        _private, public = self.ensure_identity()
        return normalize_public_key(public.read_text(encoding="utf-8"))

    def host_public_key(self, share: PeerShare) -> str:
        _private, public = self._ensure_keypair(self.root / "hosts" / share.id)
        return normalize_public_key(public.read_text(encoding="utf-8"))

    def invitation(self, share: PeerShare, role: PeerRole = PeerRole.READ_WRITE, peer_name: str = "") -> str:
        self._assign_endpoint_ports(share)
        selected_peer = self._peer_for_invitation(share, peer_name)
        if selected_peer.role is not role:
            raise PeerError("The invitation role must match the selected device's server-enforced role")
        endpoint_port = selected_peer.server_port
        transport = "tor" if share.transport_policy is PeerTransportPolicy.TOR_ONLY or share.onion_enabled else "direct"
        enforce_transport_policy(share, transport)
        client_auth = ""
        if transport == "tor" and share.onion_client_auth:
            credential = self.tor.issue_client_credential(share, selected_peer)
            client_auth = credential.private_key
        permit_relay = bool(transport == "direct" and not share.no_relay and share.transport_policy is PeerTransportPolicy.AUTO and share.relay_host and share.relay_public_port)
        relay_port = self._relay_port(share, endpoint_port) if permit_relay else 0
        allowed_transports = ("tor",) if transport == "tor" else (("direct", "relay") if permit_relay else ("direct",))
        return PeerInvitation(
            share.name,
            share.onion_address if transport == "tor" else validate_host(share.advertised_host),
            validate_port(endpoint_port),
            self.host_public_key(share),
            share.id,
            share.lease_minutes,
            share.relay_host if permit_relay else "",
            relay_port,
            role,
            transport=transport,
            onion_address=share.onion_address,
            onion_client_auth=client_auth,
            allowed_transports=allowed_transports,
        ).encode()

    def one_time_invitation(self, share: PeerShare, drop: OneTimeDrop) -> str:
        if not drop.active:
            raise PeerError("This one-time drop has expired or was already consumed")
        transport = "tor" if share.transport_policy is PeerTransportPolicy.TOR_ONLY or share.onion_enabled else "direct"
        enforce_transport_policy(share, transport)
        self._assign_endpoint_ports(share)
        permit_relay = bool(transport == "direct" and not share.no_relay and share.transport_policy is PeerTransportPolicy.AUTO and share.relay_host and share.relay_public_port)
        relay_port = self._relay_port(share, drop.server_port) if permit_relay else 0
        return PeerInvitation(
            drop.name, share.onion_address if transport == "tor" else validate_host(share.advertised_host), validate_port(drop.server_port),
            self.host_public_key(share), share.id, share.lease_minutes,
            share.relay_host if permit_relay else "", relay_port, PeerRole.SEND_ONLY,
            "", drop.id, drop.expires_at,
            transport=transport, onion_address=share.onion_address,
            allowed_transports=("tor",) if transport == "tor" else (("direct", "relay") if permit_relay else ("direct",)),
        ).encode()

    def start(self, share: PeerShare) -> None:
        folder = Path(share.local_path).expanduser().resolve(strict=False)
        if not folder.is_dir():
            raise PeerError("Select an existing local folder to share")
        port = validate_port(int(share.port))
        consumed = self.root / "drop-consumed"
        active_peers = [item for item in share.authorized_peers if item.enabled]
        if share.allowed_peer_key and not active_peers:
            active_peers = [AuthorizedPeer("Legacy peer", share.allowed_peer_key)]
        active_drops = [item for item in share.one_time_drops if item.active and not (consumed / item.id).exists()]
        if not active_peers and not active_drops:
            raise PeerError("Authorize at least one peer device before starting the share")
        self._assign_endpoint_ports(share)
        if not share.no_public_ip_discovery and share.transport_policy is not PeerTransportPolicy.TOR_ONLY:
            validate_host(share.advertised_host)
        if share.transport_policy is PeerTransportPolicy.TOR_ONLY and not share.onion_enabled:
            self._policy_violation(share, "Tor-only policy requires an enabled Onion Service")
        rclone = self._rclone()
        host_private, _host_public = self._ensure_keypair(self.root / "hosts" / share.id)
        endpoints: list[tuple[str, int, str, Path, bool, OneTimeDrop | None]] = []
        for index, peer in enumerate(active_peers):
            endpoint_root = folder
            read_only = peer.role in {PeerRole.READ_ONLY, PeerRole.RECEIVE_ONLY}
            if peer.role is PeerRole.SEND_ONLY:
                endpoint_root = confined_path(folder, Path(".tuxdrive-peer-inboxes") / _endpoint_label(peer.public_key), create_parents=True)
                endpoint_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            endpoints.append((f"{share.id}:{index}", validate_port(peer.server_port or port + index), peer.public_key, endpoint_root, read_only, None))
        for index, drop in enumerate(active_drops):
            endpoint_root = confined_path(folder, drop.inbox_path, create_parents=True)
            endpoint_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            endpoints.append((f"{share.id}:drop-{drop.id}", validate_port(drop.server_port), drop.public_key, endpoint_root, False, drop))
        if any(endpoint_id == share.id for endpoint_id, *_rest in endpoints):
            raise PeerError("Invalid peer endpoint identifier")
        started: list[tuple[str, subprocess.Popen[str], OneTimeDrop | None]] = []
        try:
            for endpoint_id, endpoint_port, public_key, endpoint_root, read_only, drop in endpoints:
                authorized = self.root / "authorized" / f"{endpoint_id.replace(':', '-')}.keys"
                authorized.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                authorized.write_text(normalize_public_key(public_key) + "\n", encoding="utf-8")
                os.chmod(authorized, 0o600)
                log_path = cache_root() / "logs" / f"peer-{endpoint_id.replace(':', '-')}.log"
                ensure_private_directory(log_path.parent)
                prepare_private_file(log_path)
                log = log_path.open("a", encoding="utf-8")
                command = [
                    rclone, "serve", "sftp", f":local:{endpoint_root}",
                    "--addr", f"127.0.0.1:{endpoint_port}" if (share.transport_policy is PeerTransportPolicy.TOR_ONLY or share.no_public_ip_discovery) else f":{endpoint_port}",
                    "--authorized-keys", str(authorized), "--key", str(host_private),
                    "--dir-cache-time", "10s", "--log-level", "INFO", "--stats", "10s", "--stats-one-line",
                ]
                if read_only:
                    command.append("--read-only")
                try:
                    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, text=True, start_new_session=True)
                except Exception:
                    log.close()
                    raise
                with self._lock:
                    self._servers[endpoint_id] = process
                    self._shares[endpoint_id] = share
                    self._logs[endpoint_id] = log
                started.append((endpoint_id, process, drop))
                threading.Thread(target=self._watch, args=(endpoint_id, process), daemon=True).start()
        except Exception:
            self.stop(share.id)
            raise
        primary_process = started[0][1]
        threading.Thread(target=self._delta_watch, args=(share, primary_process), daemon=True, name=f"peer-delta-{share.id[:8]}").start()
        for endpoint_id, process, drop in started:
            if drop:
                threading.Thread(target=self._drop_watch, args=(share, process), daemon=True, name=f"peer-drop-{drop.id[:8]}").start()
        if share.onion_enabled:
            try:
                address = self.tor.start(share, [item[1] for item in endpoints])
                self.audit.record("policy", "Onion Service published", "success", peer=share.name, detail=address)
            except Exception as exc:
                if share.transport_policy is PeerTransportPolicy.TOR_ONLY:
                    self.stop(share.id)
                self.audit.record("policy", "Onion Service unavailable", "blocked", peer=share.name, detail=str(exc))
                raise
        if share.nat_traversal and not share.no_public_ip_discovery and share.transport_policy is not PeerTransportPolicy.TOR_ONLY:
            self._nat_ports[share.id] = [item[1] for item in endpoints if self._open_nat_mapping(item[1])]
        if share.relay_host and share.relay_user and share.relay_public_port and not share.no_relay:
            try:
                self._start_relay(share, [item[1] for item in endpoints])
            except Exception:
                # Never leave a share looking healthy when its explicitly
                # configured relay could not be established.
                self.stop(share.id)
                raise

    def stop(self, share_id: str) -> bool:
        self.tor.stop(share_id)
        mapped_ports = self._nat_ports.pop(share_id, [])
        for mapped_port in mapped_ports:
            self._close_nat_mapping(mapped_port)
        tunnel = self._tunnels.pop(share_id, None)
        if tunnel and tunnel.poll() is None:
            try:
                os.killpg(tunnel.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        with self._lock:
            endpoints = [(key, process) for key, process in self._servers.items() if key == share_id or key.startswith(f"{share_id}:")]
        stopped = False
        for endpoint_id, process in endpoints:
            if process.poll() is None:
                stopped = True
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
            self._close_log(endpoint_id)
        return stopped

    @staticmethod
    def _open_nat_mapping(port: int) -> bool:
        upnpc = shutil.which("upnpc")
        if upnpc:
            result = subprocess.run(
                [upnpc, "-e", "TuxInDrive peer", "-r", str(port), "TCP"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            if result.returncode == 0:
                return True
        natpmp = shutil.which("natpmpc")
        if natpmp:
            result = subprocess.run(
                [natpmp, "-a", str(port), str(port), "tcp", "3600"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            return result.returncode == 0
        return False

    @staticmethod
    def _close_nat_mapping(port: int) -> None:
        upnpc = shutil.which("upnpc")
        if upnpc:
            subprocess.run([upnpc, "-d", str(port), "TCP"], capture_output=True, text=True, timeout=20, check=False)
        natpmp = shutil.which("natpmpc")
        if natpmp:
            subprocess.run([natpmp, "-a", str(port), str(port), "tcp", "0"], capture_output=True, text=True, timeout=20, check=False)

    def _start_relay(self, share: PeerShare, endpoint_ports: list[int]) -> None:
        ssh = shutil.which("ssh")
        if not ssh:
            raise PeerError("OpenSSH is required for the encrypted no-storage relay")
        identity, _public = self.ensure_identity()
        command = [
            ssh, "-N", "-T", "-o", "ExitOnForwardFailure=yes",
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
            "-p", str(validate_port(share.relay_ssh_port)), "-i", str(identity),
        ]
        for endpoint_port in endpoint_ports:
            command.extend(("-R", f"{self._relay_port(share, endpoint_port)}:127.0.0.1:{validate_port(endpoint_port)}"))
        command.append(f"{share.relay_user}@{validate_host(share.relay_host)}")
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self._tunnels[share.id] = process
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            return
        self._tunnels.pop(share.id, None)
        raise PeerError("The no-storage relay exited before its reverse tunnel became ready")

    def shutdown(self) -> None:
        self.discovery.stop()
        for share_id in list(self.running_shares):
            self.stop(share_id)
        self.tor.shutdown()

    def start_discovery(self) -> None:
        self.discovery.start()

    def discover(self, timeout: float = 3.5) -> list[DiscoveredPeer]:
        return LanDiscovery.discover(timeout)

    def _discovery_invitations(self) -> list[PeerInvitation]:
        with self._lock:
            shares = list({share.id: share for share in self._shares.values() if share.id in self.running_shares and share.lan_discovery}.values())
        invitations = []
        for share in shares:
            for peer in (item for item in share.authorized_peers if item.enabled):
                try:
                    invitations.append(PeerInvitation.decode(self.invitation(share, peer.role, peer.name)))
                except PeerError:
                    continue
        return invitations

    def configure_connection(
        self, remote: str, invitation: PeerInvitation, private_key: Path | None = None
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
            raise PeerError("Peer account key contains unsupported characters")
        identity_private, _identity_public = self.ensure_identity()
        key_file = private_key or identity_private
        if not key_file.is_file():
            raise PeerError("The private identity key is missing")
        rclone = self._rclone()
        if invitation.transport == "tor":
            if invitation.onion_client_auth:
                self.tor.install_client_credential(invitation.onion_address, invitation.onion_client_auth)
            self._configure_onion_connection(remote, invitation, key_file, rclone)
            return
        endpoints = [(invitation.host, invitation.port)]
        if "relay" in invitation.allowed_transports and invitation.relay_host and invitation.relay_port:
            endpoints.append((invitation.relay_host, invitation.relay_port))
        result = None
        for host, port in endpoints:
            result = subprocess.run(
                [
                rclone, "config", "create", remote, "sftp",
                "host", host,
                "port", str(port),
                "user", "tuxindrive-peer",
                "key_file", str(key_file),
                "host_keys", invitation.host_key,
                "shell_type", "none",
                "md5sum_command", "none",
                "sha1sum_command", "none",
                "--non-interactive",
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=30, check=False,
            )
            if result.returncode == 0:
                break
        if result is None or result.returncode:
            detail = "No peer endpoint was available" if result is None else (result.stderr or result.stdout).strip()[-600:]
            raise PeerError(detail)

    def _configure_onion_connection(self, remote: str, invitation: PeerInvitation, key_file: Path, rclone: str) -> None:
        torsocks = shutil.which("torsocks")
        ssh = shutil.which("ssh")
        if not torsocks or not ssh:
            raise PeerError("Tor transport needs tor, torsocks and OpenSSH; no clearnet fallback was attempted")
        try:
            torsocks_config = self.tor.start_client(remote)
        except TorError as exc:
            raise PeerError(str(exc)) from exc
        wrapper = self.root / "tor" / f"ssh-over-tor-{self.tor._safe_name(remote)}"
        ensure_private_directory(wrapper.parent)
        wrapper.write_text(f"#!/bin/sh\nexec torsocks -f {shlex.quote(str(torsocks_config))} ssh \"$@\"\n", encoding="utf-8")
        os.chmod(wrapper, 0o700)
        result = subprocess.run([
            rclone, "config", "create", remote, "sftp",
            "host", invitation.onion_address, "port", "22", "user", "tuxindrive-peer",
            "key_file", str(key_file), "host_keys", invitation.host_key,
            "ssh", str(wrapper), "shell_type", "none", "md5sum_command", "none",
            "sha1sum_command", "none", "--non-interactive",
        ], capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            raise PeerError((result.stderr or result.stdout or "Could not configure Onion peer").strip()[-600:])
        self.audit.record("peer", "Onion connection configured", "success", peer=invitation.name, detail=invitation.onion_address)

    def _policy_violation(self, share: PeerShare, detail: str) -> None:
        self.audit.record("policy", "transport blocked", "blocked", peer=share.name, detail=detail)
        raise PeerError(f"Policy violation: {detail}")

    def _rclone(self) -> str:
        resolved = resolve_rclone(self.rclone_path)
        if resolved is None:
            resolved = install_rclone()
        self.rclone_path = resolved
        return resolved

    def _ensure_keypair(self, private: Path) -> tuple[Path, Path]:
        public = private.with_suffix(".pub")
        if private.is_file() and public.is_file():
            return private, public
        keygen = shutil.which("ssh-keygen")
        if not keygen:
            raise PeerError("OpenSSH key generation is unavailable; reinstall TuxInDrive")
        private.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = subprocess.run(
            [keygen, "-q", "-t", "ed25519", "-N", "", "-C", "TuxInDrive peer", "-f", str(private)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise PeerError((result.stderr or "Could not create peer identity").strip())
        os.chmod(private, 0o600)
        os.chmod(public, 0o644)
        return private, public

    def _watch(self, share_id: str, process: subprocess.Popen[str]) -> None:
        process.wait()
        self._close_log(share_id)

    def _delta_watch(self, share: PeerShare, process: subprocess.Popen[str]) -> None:
        queue = Path(share.local_path).expanduser() / ".tuxdrive-delta"
        while process.poll() is None:
            if queue.is_dir():
                for transaction in queue.iterdir():
                    instruction = transaction / "instruction.json"
                    if instruction.is_file():
                        try:
                            changed_path = self._apply_delta_transaction(
                                Path(share.local_path).expanduser(), transaction,
                                [item.public_key for item in share.authorized_peers if item.enabled],
                            )
                            self.audit.record("peer", "block delta applied", "success", path=changed_path, detail=share.name)
                        except (OSError, ValueError, KeyError, json.JSONDecodeError):
                            continue
            time.sleep(1.0)

    def _drop_watch(self, share: PeerShare, process: subprocess.Popen[str]) -> None:
        root = Path(share.local_path).expanduser()
        markers = self.root / "drop-consumed"
        markers.mkdir(parents=True, exist_ok=True, mode=0o700)
        while process.poll() is None:
            for drop in share.one_time_drops:
                marker = markers / drop.id
                inbox = root / drop.inbox_path
                if marker.exists() or not drop.active or not inbox.is_dir():
                    continue
                try:
                    uploaded = next((item for item in inbox.rglob("*") if item.is_file()), None)
                except OSError:
                    uploaded = None
                if uploaded:
                    marker.touch(mode=0o600, exist_ok=True)
                    drop.consumed = True
                    self.audit.record("peer", "one-time drop consumed", "success", peer=drop.name, path=drop.inbox_path, detail=uploaded.name)
                    threading.Thread(
                        target=self._restart_after_drop, args=(share,), daemon=True,
                        name=f"peer-drop-revoke-{share.id[:8]}",
                    ).start()
                    return
            time.sleep(1.0)

    def _restart_after_drop(self, share: PeerShare) -> None:
        """Rebuild authorized keys and terminate sessions after a drop is consumed."""
        self.stop(share.id)
        if share.enabled:
            try:
                self.start(share)
            except PeerError as exc:
                self.audit.record("peer", "one-time drop key revocation", "blocked", peer=share.name, detail=str(exc))

    @staticmethod
    def _apply_delta_transaction(root: Path, transaction: Path, authorized_keys: list[str]) -> str:
        value = json.loads((transaction / "instruction.json").read_text(encoding="utf-8"))
        signer = normalize_public_key(str(value.pop("signer")))
        signature = str(value.pop("signature"))
        normalized_allowed = {normalize_public_key(item) for item in authorized_keys}
        if signer not in normalized_allowed:
            raise ValueError("delta signer is not authorized")
        verify_signed_json(value, signer, signature)
        relative = Path(str(value["path"]))
        expected_size = int(value["size"])
        blocks_value = value.get("blocks", [])
        if expected_size < 0 or expected_size > 16 * 1024 * 1024 * 1024 or len(blocks_value) > 65536:
            raise ValueError("delta transaction exceeds safety limits")
        with confined_parent(root, relative, create_parents=True) as (parent_fd, target_name, normalized):
            temporary_name = f".{target_name}.{uuid4().hex}.tuxdrive-delta"
            temporary_fd = os.open(temporary_name, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent_fd)
            try:
                try:
                    source_fd = os.open(target_name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
                except FileNotFoundError:
                    source_fd = None
                if source_fd is not None:
                    with os.fdopen(source_fd, "rb") as source, os.fdopen(os.dup(temporary_fd), "wb") as output:
                        shutil.copyfileobj(source, output)
                with os.fdopen(os.dup(temporary_fd), "r+b") as handle:
                    for block in blocks_value:
                        offset, size = int(block["offset"]), int(block["size"])
                        if offset < 0 or size < 0 or size > 64 * 1024 * 1024 or offset + size > expected_size:
                            raise ValueError("invalid delta block bounds")
                        content = (transaction / "blocks" / f"{offset:016x}.block").read_bytes()
                        if len(content) != size or hashlib.blake2b(content, digest_size=32).hexdigest() != block["digest"]:
                            raise ValueError("delta block integrity failure")
                        handle.seek(offset)
                        handle.write(content)
                    handle.truncate(expected_size)
                digest = hashlib.sha256()
                os.lseek(temporary_fd, 0, os.SEEK_SET)
                with os.fdopen(os.dup(temporary_fd), "rb") as handle:
                    while chunk := handle.read(4 * 1024 * 1024):
                        digest.update(chunk)
                if digest.hexdigest() != value["sha256"]:
                    raise ValueError("delta file integrity failure")
                os.replace(temporary_name, target_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                shutil.rmtree(transaction)
                return normalized.as_posix()
            finally:
                os.close(temporary_fd)
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass

    def _close_log(self, share_id: str) -> None:
        with self._lock:
            log = self._logs.pop(share_id, None)
            self._servers.pop(share_id, None)
            self._shares.pop(share_id, None)
        if log:
            log.close()
