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
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .bootstrap import install_rclone, resolve_rclone
from .config import cache_home, config_home
from .models import PeerShare, SyncJob


class PeerError(RuntimeError):
    pass


PUBLIC_KEY = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/]+={0,3}(?: .*)?$"
)


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

    def encode(self) -> str:
        return json.dumps(
            {
                "tuxdrive_peer": 3,
                "name": self.name,
                "host": self.host,
                "port": self.port,
                "host_key": self.host_key,
                "share_id": self.share_id,
                "lease_minutes": self.lease_minutes,
                "relay_host": self.relay_host,
                "relay_port": self.relay_port,
            },
            indent=2,
        )

    @classmethod
    def decode(cls, value: str) -> "PeerInvitation":
        try:
            data = json.loads(value)
            if data.get("tuxdrive_peer") not in (1, 2, 3):
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
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PeerError("The peer invitation is incomplete or invalid") from exc
        return invitation


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
                    payload = json.dumps({"tuxdrive_lan": 1, **json.loads(invitation.encode())}).encode("utf-8")
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
                    if data.get("tuxdrive_lan") != 1:
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
        self.root = root or config_home() / "tuxdrive" / "peer"
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
    """Runs direct, mutually authenticated SFTP shares between TuxDrive peers."""

    def __init__(self, rclone_path: str = "rclone", root: Path | None = None) -> None:
        self.rclone_path = rclone_path
        self.root = root or config_home() / "tuxdrive" / "peer"
        self._servers: dict[str, subprocess.Popen[str]] = {}
        self._shares: dict[str, PeerShare] = {}
        self._logs: dict[str, object] = {}
        self._tunnels: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.RLock()
        self.discovery = LanDiscovery(self._discovery_invitations)

    @property
    def running_shares(self) -> set[str]:
        with self._lock:
            return {
                share_id for share_id, process in self._servers.items()
                if process.poll() is None
            }

    def ensure_identity(self) -> tuple[Path, Path]:
        return self._ensure_keypair(self.root / "identity_ed25519")

    def identity_public_key(self) -> str:
        _private, public = self.ensure_identity()
        return normalize_public_key(public.read_text(encoding="utf-8"))

    def host_public_key(self, share: PeerShare) -> str:
        _private, public = self._ensure_keypair(self.root / "hosts" / share.id)
        return normalize_public_key(public.read_text(encoding="utf-8"))

    def invitation(self, share: PeerShare) -> str:
        return PeerInvitation(
            share.name,
            validate_host(share.advertised_host),
            validate_port(int(share.port)),
            self.host_public_key(share),
            share.id,
            share.lease_minutes,
            share.relay_host,
            share.relay_public_port,
        ).encode()

    def start(self, share: PeerShare) -> None:
        folder = Path(share.local_path).expanduser().resolve(strict=False)
        if not folder.is_dir():
            raise PeerError("Select an existing local folder to share")
        port = validate_port(int(share.port))
        allowed_keys = list(dict.fromkeys(normalize_public_key(value) for value in share.active_peer_keys))
        if not allowed_keys:
            raise PeerError("Authorize at least one peer device before starting the share")
        validate_host(share.advertised_host)
        rclone = self._rclone()
        host_private, _host_public = self._ensure_keypair(self.root / "hosts" / share.id)
        authorized = self.root / "authorized" / f"{share.id}.keys"
        authorized.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        authorized.write_text("\n".join(allowed_keys) + "\n", encoding="utf-8")
        os.chmod(authorized, 0o600)
        log_path = cache_home() / "tuxdrive" / "logs" / f"peer-{share.id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            current = self._servers.get(share.id)
            if current and current.poll() is None:
                return
            log = log_path.open("a", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    [
                        rclone, "serve", "sftp", f":local:{folder}",
                        "--addr", f":{port}",
                        "--authorized-keys", str(authorized),
                        "--key", str(host_private),
                        "--dir-cache-time", "10s",
                        "--log-level", "INFO",
                        "--stats", "10s",
                        "--stats-one-line",
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
            except Exception:
                log.close()
                raise
            self._servers[share.id] = process
            self._shares[share.id] = share
            self._logs[share.id] = log
        threading.Thread(target=self._watch, args=(share.id, process), daemon=True).start()
        threading.Thread(target=self._delta_watch, args=(share, process), daemon=True, name=f"peer-delta-{share.id[:8]}").start()
        if share.nat_traversal:
            self._open_nat_mapping(port)
        if share.relay_host and share.relay_user and share.relay_public_port:
            try:
                self._start_relay(share)
            except Exception:
                # Never leave a share looking healthy when its explicitly
                # configured relay could not be established.
                self.stop(share.id)
                raise

    def stop(self, share_id: str) -> bool:
        tunnel = self._tunnels.pop(share_id, None)
        if tunnel and tunnel.poll() is None:
            try:
                os.killpg(tunnel.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        with self._lock:
            process = self._servers.get(share_id)
        if not process or process.poll() is not None:
            self._close_log(share_id)
            return False
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        self._close_log(share_id)
        return True

    @staticmethod
    def _open_nat_mapping(port: int) -> bool:
        upnpc = shutil.which("upnpc")
        if upnpc:
            result = subprocess.run(
                [upnpc, "-e", "TuxDrive peer", "-r", str(port), "TCP"],
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

    def _start_relay(self, share: PeerShare) -> None:
        ssh = shutil.which("ssh")
        if not ssh:
            raise PeerError("OpenSSH is required for the encrypted no-storage relay")
        identity, _public = self.ensure_identity()
        command = [
            ssh, "-N", "-T", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
            "-p", str(validate_port(share.relay_ssh_port)), "-i", str(identity),
            "-R", f"{validate_port(share.relay_public_port)}:127.0.0.1:{validate_port(share.port)}",
            f"{share.relay_user}@{validate_host(share.relay_host)}",
        ]
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

    def start_discovery(self) -> None:
        self.discovery.start()

    def discover(self, timeout: float = 3.5) -> list[DiscoveredPeer]:
        return LanDiscovery.discover(timeout)

    def _discovery_invitations(self) -> list[PeerInvitation]:
        with self._lock:
            shares = [share for share_id, share in self._shares.items() if share_id in self.running_shares and share.lan_discovery]
        invitations = []
        for share in shares:
            try:
                invitations.append(PeerInvitation.decode(self.invitation(share)))
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
        endpoints = [(invitation.host, invitation.port)]
        if invitation.relay_host and invitation.relay_port:
            endpoints.append((invitation.relay_host, invitation.relay_port))
        result = None
        for host, port in endpoints:
            result = subprocess.run(
                [
                rclone, "config", "create", remote, "sftp",
                "host", host,
                "port", str(port),
                "user", "tuxdrive-peer",
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
            raise PeerError("OpenSSH key generation is unavailable; reinstall TuxDrive")
        private.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = subprocess.run(
            [keygen, "-q", "-t", "ed25519", "-N", "", "-C", "TuxDrive peer", "-f", str(private)],
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
                            self._apply_delta_transaction(Path(share.local_path).expanduser(), transaction)
                        except (OSError, ValueError, KeyError, json.JSONDecodeError):
                            continue
            time.sleep(1)

    @staticmethod
    def _apply_delta_transaction(root: Path, transaction: Path) -> None:
        value = json.loads((transaction / "instruction.json").read_text(encoding="utf-8"))
        relative = Path(str(value["path"]))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("unsafe delta path")
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tuxdrive-delta")
        if target.is_file():
            shutil.copy2(target, temporary)
        else:
            temporary.touch()
        try:
            with temporary.open("r+b") as handle:
                for block in value.get("blocks", []):
                    offset, size = int(block["offset"]), int(block["size"])
                    content = (transaction / "blocks" / f"{offset:016x}.block").read_bytes()
                    if len(content) != size or hashlib.blake2b(content, digest_size=32).hexdigest() != block["digest"]:
                        raise ValueError("delta block integrity failure")
                    handle.seek(offset)
                    handle.write(content)
                handle.truncate(int(value["size"]))
            digest = hashlib.sha256()
            with temporary.open("rb") as handle:
                while chunk := handle.read(4 * 1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != value["sha256"]:
                raise ValueError("delta file integrity failure")
            os.replace(temporary, target)
            shutil.rmtree(transaction)
        finally:
            temporary.unlink(missing_ok=True)

    def _close_log(self, share_id: str) -> None:
        with self._lock:
            log = self._logs.pop(share_id, None)
            self._servers.pop(share_id, None)
            self._shares.pop(share_id, None)
        if log:
            log.close()
