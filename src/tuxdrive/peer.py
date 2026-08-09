from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from .bootstrap import install_rclone, resolve_rclone
from .config import cache_home, config_home
from .models import PeerShare


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

    def encode(self) -> str:
        return json.dumps(
            {
                "tuxdrive_peer": 1,
                "name": self.name,
                "host": self.host,
                "port": self.port,
                "host_key": self.host_key,
            },
            indent=2,
        )

    @classmethod
    def decode(cls, value: str) -> "PeerInvitation":
        try:
            data = json.loads(value)
            if data.get("tuxdrive_peer") != 1:
                raise ValueError
            invitation = cls(
                name=str(data.get("name") or "Peer folder"),
                host=validate_host(str(data["host"])),
                port=validate_port(int(data["port"])),
                host_key=normalize_public_key(str(data["host_key"])),
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


class PeerManager:
    """Runs direct, mutually authenticated SFTP shares between TuxDrive peers."""

    def __init__(self, rclone_path: str = "rclone", root: Path | None = None) -> None:
        self.rclone_path = rclone_path
        self.root = root or config_home() / "tuxdrive" / "peer"
        self._servers: dict[str, subprocess.Popen[str]] = {}
        self._logs: dict[str, object] = {}
        self._lock = threading.RLock()

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
        ).encode()

    def start(self, share: PeerShare) -> None:
        folder = Path(share.local_path).expanduser().resolve(strict=False)
        if not folder.is_dir():
            raise PeerError("Select an existing local folder to share")
        port = validate_port(int(share.port))
        allowed_key = normalize_public_key(share.allowed_peer_key)
        validate_host(share.advertised_host)
        rclone = self._rclone()
        host_private, _host_public = self._ensure_keypair(self.root / "hosts" / share.id)
        authorized = self.root / "authorized" / f"{share.id}.keys"
        authorized.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        authorized.write_text(allowed_key + "\n", encoding="utf-8")
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
            self._logs[share.id] = log
        threading.Thread(target=self._watch, args=(share.id, process), daemon=True).start()

    def stop(self, share_id: str) -> bool:
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

    def shutdown(self) -> None:
        for share_id in list(self.running_shares):
            self.stop(share_id)

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
        result = subprocess.run(
            [
                rclone, "config", "create", remote, "sftp",
                "host", invitation.host,
                "port", str(invitation.port),
                "user", "tuxdrive-peer",
                "key_file", str(key_file),
                "host_keys", invitation.host_key,
                "shell_type", "none",
                "md5sum_command", "none",
                "sha1sum_command", "none",
                "--non-interactive",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            raise PeerError((result.stderr or result.stdout).strip()[-600:])

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

    def _close_log(self, share_id: str) -> None:
        with self._lock:
            log = self._logs.pop(share_id, None)
            self._servers.pop(share_id, None)
        if log:
            log.close()
