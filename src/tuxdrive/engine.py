from __future__ import annotations

import errno
import os
import platform
import re
import shutil
import signal
import subprocess
import threading
import time
import json
import tempfile
import uuid
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .bootstrap import install_rclone, resolve_rclone
from .callbacks import ChangeMonitor, FileChange, TRANSIENT_PATTERNS, is_transient_path
from .config import cache_home, config_home
from .models import ConflictPolicy, PeerRole, SyncJob, SyncMode
from .recovery import MassChangeGuard, RecoveryManager
from .peer import PeerError, PeerLeaseManager
from .delta import BlockDeltaPlanner, BlockSignature
from .github_sync import GitHubSyncError, parse_repository_url, validate_branch
from .security import UnsafePathError, confined_path, ensure_private_directory, prepare_private_file, sign_json, install_confined, unlink_confined
from .nautilus_support import is_available_offline


@dataclass(slots=True)
class JobResult:
    job_id: str
    success: bool
    message: str
    log_path: Path
    cancelled: bool = False
    requires_resync: bool = False
    blocked_path: str = ""
    incremental: bool = False
    mount_lost: bool = False
    mass_change_blocked: bool = False
    lease_blocked: bool = False


class SyncEngine:
    def __init__(self, rclone_path: str = "rclone") -> None:
        self.rclone_path = rclone_path
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._mounts: dict[str, subprocess.Popen[str]] = {}
        self._mount_paths: dict[str, Path] = {}
        self._monitors: dict[str, ChangeMonitor] = {}
        self._intentional_unmounts: set[str] = set()
        self._protected_patterns: dict[str, tuple[str, ...]] = {}
        self.recovery = RecoveryManager()
        self.leases = PeerLeaseManager(rclone_path)
        self._lock = threading.RLock()
        self.delta = BlockDeltaPlanner()

    @property
    def running_jobs(self) -> set[str]:
        with self._lock:
            return set(self._processes)

    @property
    def mounted_jobs(self) -> set[str]:
        with self._lock:
            return {
                job_id for job_id, process in self._mounts.items() if process.poll() is None
            }

    @property
    def callback_jobs(self) -> set[str]:
        with self._lock:
            return set(self._monitors)

    def configure_jobs(self, jobs: list[SyncJob]) -> None:
        protected: dict[str, list[str]] = {}
        for parent in jobs:
            if parent.mode is SyncMode.VIRTUAL_DRIVE:
                continue
            for streamed in jobs:
                if streamed.mode is not SyncMode.VIRTUAL_DRIVE:
                    continue
                try:
                    relative = streamed.local.resolve(strict=False).relative_to(
                        parent.local.resolve(strict=False)
                    ).as_posix()
                except ValueError:
                    continue
                if relative and relative != ".":
                    protected.setdefault(parent.id, []).extend(
                        [f"/{relative}", f"/{relative}/**"]
                    )
        self._protected_patterns = {
            job_id: tuple(dict.fromkeys(patterns))
            for job_id, patterns in protected.items()
        }

    def command_for_job(self, job: SyncJob, dry_run: bool = False) -> list[str]:
        local = str(job.local)
        common = [
            "--create-empty-src-dirs",
            "--transfers",
            "4",
            "--checkers",
            "8",
            "--stats",
            "5s",
            "--stats-one-line",
            "--log-level",
            "INFO",
            "--max-delete",
            str(max(0, job.max_delete)),
            "--track-renames",
            "--track-renames-strategy",
            "modtime,leaf",
        ]
        if job.acknowledge_google_abuse:
            common.append("--drive-acknowledge-abuse")
        for pattern in dict.fromkeys([
            *job.exclude_patterns,
            *self._protected_patterns.get(job.id, ()),
            *TRANSIENT_PATTERNS,
            "/.tuxdrive-versions/**",
            "/.tuxdrive-leases/**",
            "/.tuxdrive-delta/**",
            "/.tuxdrive-drops/**",
        ]):
            if pattern.strip():
                common.extend(["--exclude", pattern.strip()])
        if job.bandwidth_limit.strip():
            common.extend(["--bwlimit", job.bandwidth_limit.strip()])
        if dry_run:
            common.append("--dry-run")

        if job.version_history:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            local_history = self.recovery.root / job.id / "rclone" / stamp
            remote_root = job.remote_spec.split(":", 1)[0] + ":"
            remote_history = (
                f"{remote_root}.tuxdrive-versions/{job.id}/{stamp}"
            )

        if job.mode is SyncMode.TWO_WAY:
            command = [self.rclone_path, "bisync", local, job.remote_spec]
            command.extend(["--resilient", "--recover", "--conflict-loser", "pathname"])
            command.extend(self._conflict_flags(job.conflict_policy))
            workdir = cache_home() / "tuxdrive" / "bisync" / job.id
            command.extend(["--workdir", str(workdir)])
            if job.version_history:
                command.extend([
                    "--backup-dir1", str(local_history),
                    "--backup-dir2", remote_history,
                    "--suffix", f".{stamp}.tuxdrive-version",
                    "--suffix-keep-extension",
                    "--conflict-suffix", "{DateOnly}-tuxdrive-conflict",
                ])
            if not job.initialized:
                command.extend(["--resync", "--resync-mode", "newer"])
            return [*command, *common]

        if job.mode is SyncMode.DOWNLOAD_ONLY:
            history = ["--backup-dir", str(local_history)] if job.version_history else []
            action = "copy" if job.peer_role is PeerRole.READ_ONLY else "sync"
            return [self.rclone_path, action, job.remote_spec, local, *history, *common]
        if job.mode is SyncMode.UPLOAD_ONLY:
            history = ["--backup-dir", remote_history] if job.version_history else []
            return [self.rclone_path, "sync", local, job.remote_spec, *history, *common]
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            return self.mount_command(job)
        raise ValueError(f"Unsupported sync mode: {job.mode}")

    def mount_command(self, job: SyncJob) -> list[str]:
        cache = cache_home() / "tuxdrive" / "vfs" / job.id
        command = [
            self.rclone_path,
            "mount",
            job.remote_spec,
            str(job.local),
            "--vfs-cache-mode",
            "full",
            "--vfs-read-chunk-size",
            "8M",
            "--vfs-read-chunk-size-limit",
            "128M",
            "--vfs-read-chunk-streams",
            "4",
            "--vfs-cache-max-age",
            "24h",
            "--vfs-cache-max-size",
            "10G",
            "--vfs-cache-min-free-space",
            "1G",
            "--vfs-cache-poll-interval",
            "1m",
            "--vfs-write-back",
            "5s",
            "--cache-dir",
            str(cache),
            "--dir-cache-time",
            "5m",
            "--poll-interval",
            "30s",
            "--log-level",
            "INFO",
            "--stats",
            "10s",
            "--stats-one-line",
            "--umask",
            "022",
        ]
        if job.offline_paths:
            # A generic rclone cache quota cannot distinguish pinned content
            # from ordinary streamed files: it evicts the least recently used
            # object regardless of TuxDrive's offline rules.  Disable those
            # automatic eviction paths while at least one durable pin exists;
            # the explicit Free local space action remains the authority for
            # releasing pinned bytes.  Fast fingerprints avoid a slow remote
            # hash/modtime round-trip when opening an already cached file.
            index = command.index("--vfs-cache-max-age")
            command[index + 1] = "87600h"
            index = command.index("--vfs-cache-max-size")
            command[index + 1] = "off"
            index = command.index("--vfs-cache-min-free-space")
            command[index + 1] = "off"
            command.append("--vfs-fast-fingerprint")
        return command

    @staticmethod
    def _cache_relative_matches(cache_relative: str, selected: str, *, directory: bool = True) -> bool:
        if selected == ".":
            return True
        parts = Path(cache_relative).parts
        wanted = Path(selected).parts
        for index in range(0, len(parts) - len(wanted) + 1):
            if parts[index:index + len(wanted)] != wanted:
                continue
            if directory or index + len(wanted) == len(parts):
                return True
        return False

    @staticmethod
    def _pin_marker(job: SyncJob, relative: str) -> Path:
        key = hashlib.sha256(relative.encode("utf-8")).hexdigest()
        return cache_home() / "tuxdrive" / "vfs" / job.id / ".tuxdrive-pins" / f"{key}.json"

    def _record_pin_cache(self, job: SyncJob, relative: str, hydrated_files: list[str]) -> None:
        cache = cache_home() / "tuxdrive" / "vfs" / job.id
        data_root = cache / "vfs"
        records: list[dict[str, int | str]] = []
        candidates = [item for item in data_root.rglob("*") if item.is_file()] if data_root.exists() else []
        for hydrated_relative in hydrated_files:
            mounted_relative = "/".join(
                part for part in (job.remote_path.strip("/"), hydrated_relative.strip("/")) if part
            )
            matches = [
                item for item in candidates
                if self._cache_relative_matches(
                    item.relative_to(data_root).as_posix(), mounted_relative, directory=False
                )
            ]
            if not matches:
                raise RuntimeError(
                    f"TuxDrive read {hydrated_relative}, but rclone did not persist a verifiable cache file"
                )
            # A per-job cache should normally produce one exact suffix match.
            # Prefer the shortest prefix if a remote path repeats names.
            item = min(matches, key=lambda value: len(value.parts))
            cache_relative = item.relative_to(data_root).as_posix()
            stat = item.stat()
            records.append({
                "path": cache_relative,
                "size": stat.st_size,
                "blocks": getattr(stat, "st_blocks", 0),
            })
        marker = self._pin_marker(job, relative)
        ensure_private_directory(marker.parent)
        descriptor, temporary = tempfile.mkstemp(prefix="pin-", suffix=".json", dir=marker.parent)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"relative": relative, "files": records}, handle, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, marker)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def verified_offline_rules(self, job: SyncJob) -> set[str]:
        """Verify pin markers and VFS files without reading from the remote mount."""
        data_root = cache_home() / "tuxdrive" / "vfs" / job.id / "vfs"
        verified: set[str] = set()
        for relative in job.offline_paths:
            marker = self._pin_marker(job, relative)
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
                if payload.get("relative") != relative or not isinstance(payload.get("files"), list):
                    continue
                valid = True
                for record in payload["files"]:
                    cache_relative = str(record["path"])
                    cache_path = Path(cache_relative)
                    if cache_path.is_absolute() or ".." in cache_path.parts or not cache_path.parts:
                        valid = False
                        break
                    # A more specific online-only rule deliberately releases
                    # this part of an otherwise pinned parent.
                    if any(
                        self._cache_relative_matches(
                            cache_relative,
                            "/".join(
                                part for part in (job.remote_path.strip("/"), rule.strip("/")) if part
                            ),
                        )
                        and not is_available_offline(rule, job.offline_paths, job.online_only_paths)
                        for rule in job.online_only_paths
                    ):
                        continue
                    item = data_root / cache_path
                    stat = item.stat()
                    if stat.st_size != int(record["size"]):
                        valid = False
                        break
                    recorded_blocks = int(record.get("blocks", 0))
                    if recorded_blocks and getattr(stat, "st_blocks", 0) < recorded_blocks:
                        valid = False
                        break
                if valid:
                    verified.add(relative)
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return verified

    def set_offline(self, job: SyncJob, relative: str, available: bool) -> str:
        relative = relative.strip("/")
        relative_path = Path(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or ".." in relative_path.parts
            or (relative != "." and not relative_path.parts)
        ):
            raise ValueError("Select a file or folder inside the streaming drive")
        if available:
            previous_rules = list(job.offline_paths)
            previous_online_only = list(job.online_only_paths)
            if relative == ".":
                job.offline_paths = ["."]
                job.online_only_paths.clear()
            else:
                job.offline_paths = [
                    rule for rule in previous_rules
                    if not rule.startswith(relative.rstrip("/") + "/")
                ]
                if relative not in job.offline_paths:
                    job.offline_paths.append(relative)
                job.online_only_paths = [
                    rule for rule in previous_online_only
                    if rule != relative and not rule.startswith(relative.rstrip("/") + "/")
                ]
            try:
                target = (
                    job.local.expanduser().resolve(strict=True)
                    if relative == "."
                    else confined_path(job.local, relative)
                )
                files = 0
                hydrated = 0
                hydrated_files: list[str] = []

                def hydrate(item: Path, item_relative: str) -> None:
                    nonlocal files, hydrated
                    if item.is_symlink():
                        raise ValueError(f"Cannot pin symbolic link: {item.name}")
                    with item.open("rb") as handle:
                        while content := handle.read(4 * 1024 * 1024):
                            hydrated += len(content)
                    files += 1
                    hydrated_files.append(item_relative)

                is_directory = target.is_dir()
                if target.is_file():
                    hydrate(target, relative)
                elif is_directory:
                    for item in target.rglob("*"):
                        if item.is_file():
                            relative_item = item.relative_to(job.local)
                            hydrate(confined_path(job.local, relative_item), relative_item.as_posix())
                else:
                    raise ValueError("The selected streaming item is no longer available")
                self._record_pin_cache(job, relative, hydrated_files)
                return f"Available offline · {files} file(s) · {hydrated} bytes hydrated"
            except Exception:
                job.offline_paths = previous_rules
                job.online_only_paths = previous_online_only
                raise
        previous_rules = list(job.offline_paths)
        if relative == ".":
            job.offline_paths.clear()
            job.online_only_paths.clear()
        else:
            job.offline_paths = [item for item in job.offline_paths if item != relative and not item.startswith(relative + "/")]
            job.online_only_paths = [
                item for item in job.online_only_paths
                if item != relative and not item.startswith(relative + "/")
            ]
            if is_available_offline(relative, job.offline_paths, job.online_only_paths):
                job.online_only_paths.append(relative)
        for rule in previous_rules:
            if rule not in job.offline_paths:
                self._pin_marker(job, rule).unlink(missing_ok=True)
        cache = cache_home() / "tuxdrive" / "vfs" / job.id
        if relative == "." and cache.exists():
            shutil.rmtree(cache)
            return "Online only; streaming cache released"
        marker = "/" + relative.rstrip("/")
        for item in (cache.rglob("*") if cache.exists() else ()):
            path = item.as_posix()
            if item.is_file() and (path.endswith(marker) or marker + "/" in path):
                item.unlink(missing_ok=True)
        return "Online only; matching cached content released"

    def restart_mount(
        self,
        job: SyncJob,
        callback: Callable[[JobResult], None],
    ) -> JobResult:
        """Restart a live VFS after its durable-retention policy changes."""
        self.stop_mount(job)
        result = self.start_mount(job)
        if result.success:
            with self._lock:
                process = self._mounts.get(job.id)
            if process:
                threading.Thread(
                    target=self._watch_mount,
                    args=(job, process, result.log_path, callback),
                    name=f"tuxdrive-mount-{job.id[:8]}",
                    daemon=True,
                ).start()
        return result

    def record_delta_manifest(self, job: SyncJob, relative: str) -> tuple[int, int]:
        """Persist rolling-block signatures and report changed/total bytes."""
        source = confined_path(job.local, relative)
        if not source.is_file():
            return 0, 0
        root = cache_home() / "tuxdrive" / "delta" / job.id
        root.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(relative.encode("utf-8")).hexdigest()
        manifest = root / f"{key}.json"
        previous = []
        try:
            previous = [BlockSignature(**item) for item in json.loads(manifest.read_text(encoding="utf-8"))]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        current = self.delta.signatures(source)
        changed = self.delta.changed(current, previous)
        temporary = manifest.with_suffix(".tmp")
        temporary.write_text(json.dumps([{"offset": item.offset, "size": item.size, "digest": item.digest} for item in current]), encoding="utf-8")
        os.replace(temporary, manifest)
        return self.delta.transferred_bytes(changed), sum(item.size for item in current)

    def transfer_peer_delta(self, job: SyncJob, relative: str, log) -> bool:
        """Upload only changed blocks plus an authenticated peer-side transaction."""
        source = confined_path(job.local, relative)
        if not source.is_file():
            return False
        root = cache_home() / "tuxdrive" / "delta" / job.id
        root.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(relative.encode("utf-8")).hexdigest()
        manifest = root / f"{key}.json"
        try:
            previous = [BlockSignature(**item) for item in json.loads(manifest.read_text(encoding="utf-8"))]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            previous = []
        current = self.delta.signatures(source)
        changed = self.delta.changed(current, previous)
        transaction = uuid.uuid4().hex
        remote_root = f"{job.remote_spec.rstrip('/')}/.tuxdrive-delta/{transaction}"
        with tempfile.TemporaryDirectory(prefix="tuxdrive-delta-") as folder:
            temporary = Path(folder)
            blocks = temporary / "blocks"
            blocks.mkdir()
            with source.open("rb") as handle:
                for block in changed:
                    handle.seek(block.offset)
                    (blocks / f"{block.offset:016x}.block").write_bytes(handle.read(block.size))
            file_digest = hashlib.sha256()
            with source.open("rb") as source_handle:
                while content := source_handle.read(4 * 1024 * 1024):
                    file_digest.update(content)
            instruction = {
                "version": 1, "path": relative, "size": source.stat().st_size,
                "sha256": file_digest.hexdigest(),
                "blocks": [{"offset": item.offset, "size": item.size, "digest": item.digest} for item in changed],
            }
            identity = config_home() / "tuxdrive" / "peer" / "identity_ed25519"
            try:
                signer, signature = sign_json(instruction, identity)
            except (OSError, ValueError):
                return False
            instruction.update({"signer": signer, "signature": signature})
            if changed:
                first = subprocess.run(
                    [self.rclone_path, "copy", str(blocks), f"{remote_root}/blocks"],
                    stdout=log, stderr=subprocess.STDOUT, text=True, check=False,
                )
                if first.returncode:
                    return False
            instruction_path = temporary / "instruction.json"
            instruction_path.write_text(json.dumps(instruction), encoding="utf-8")
            final = subprocess.run(
                [self.rclone_path, "copyto", str(instruction_path), f"{remote_root}/instruction.json"],
                stdout=log, stderr=subprocess.STDOUT, text=True, check=False,
            )
            if final.returncode:
                return False
        temporary_manifest = manifest.with_suffix(".tmp")
        temporary_manifest.write_text(json.dumps([{"offset": item.offset, "size": item.size, "digest": item.digest} for item in current]), encoding="utf-8")
        os.replace(temporary_manifest, manifest)
        log.write(f"Block delta transfer: {relative}: {sum(item.size for item in changed)}/{source.stat().st_size} bytes\n")
        return True

    def run_async(
        self,
        job: SyncJob,
        callback: Callable[[JobResult], None],
        dry_run: bool = False,
    ) -> bool:
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            result = self.start_mount(job)
            callback(result)
            if result.success:
                with self._lock:
                    process = self._mounts.get(job.id)
                if process:
                    threading.Thread(
                        target=self._watch_mount,
                        args=(job, process, result.log_path, callback),
                        name=f"tuxdrive-mount-{job.id[:8]}",
                        daemon=True,
                    ).start()
            return result.success
        with self._lock:
            if job.id in self._processes:
                return False
        job.local.mkdir(parents=True, exist_ok=True)
        log_path = self._log_path(job)
        thread = threading.Thread(
            target=self._run_worker,
            args=(job, log_path, callback, dry_run),
            name=f"tuxdrive-sync-{job.id[:8]}",
            daemon=True,
        )
        thread.start()
        return True

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            process = self._processes.get(job_id)
        if not process or process.poll() is not None:
            return False
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        return True

    def start_mount(self, job: SyncJob) -> JobResult:
        log_path = self._log_path(job)
        with self._lock:
            existing = self._mounts.get(job.id)
            if existing and existing.poll() is None:
                return JobResult(job.id, True, "Virtual drive is already mounted", log_path)
        # Detach an untracked/orphaned mount before touching the directory.
        # Calling mkdir/iterdir on a dead FUSE endpoint raises ENOTCONN.
        if os.path.ismount(job.local):
            self._unmount_path(job.local)
            deadline = time.monotonic() + 5
            while os.path.ismount(job.local) and time.monotonic() < deadline:
                time.sleep(0.1)
            if os.path.ismount(job.local):
                return JobResult(
                    job.id, False,
                    "An existing streaming mount could not be detached. Log out and back in, then retry.",
                    log_path,
                )
        try:
            job.local.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if exc.errno == errno.ENOTCONN and self._unmount_path(job.local):
                try:
                    job.local.mkdir(parents=True, exist_ok=True)
                except OSError as retry_exc:
                    return JobResult(job.id, False, f"Cannot prepare streaming mount point: {retry_exc}", log_path)
            else:
                return JobResult(job.id, False, f"Cannot prepare streaming mount point: {exc}", log_path)
        if not os.path.ismount(job.local):
            try:
                contents = list(job.local.iterdir())
            except OSError as exc:
                return JobResult(job.id, False, f"Cannot access streaming mount point: {exc}", log_path)
            if contents:
                return JobResult(
                    job.id,
                    False,
                    "Streaming drive needs an empty local folder as its mount point. Edit the job and choose "
                    "an empty folder; it may be an excluded child of a synchronized folder.",
                    log_path,
                )
        prepare_private_file(log_path)
        is_macos = platform.system() == "Darwin"
        fuse_available = (
            Path("/Library/Filesystems/macfuse.fs").exists() if is_macos else Path("/dev/fuse").exists()
        )
        unmount_tool = shutil.which("umount") if is_macos else (shutil.which("fusermount3") or shutil.which("fusermount"))
        with log_path.open("a", encoding="utf-8") as diagnostic:
            diagnostic.write(
                f"\n[{datetime.now(timezone.utc).isoformat()}] Streaming preflight\n"
                f"TuxDrive={__version__}\nRemote={job.remote_spec}\nMountPoint={job.local}\n"
                f"Rclone={self.rclone_path}\nFuseAvailable={fuse_available}\n"
                f"UnmountTool={unmount_tool or 'missing'}\n"
            )
        if not fuse_available:
            return JobResult(
                job.id, False,
                "Streaming requires macFUSE on macOS or /dev/fuse on Linux, but it is unavailable. See the job log.",
                log_path,
            )
        if not unmount_tool:
            return JobResult(
                job.id, False,
                "Streaming requires a supported FUSE unmount tool, but it is unavailable.",
                log_path,
            )
        prepare_private_file(log_path)
        log_handle = log_path.open("a", encoding="utf-8")
        log_handle.write(
            f"[{datetime.now(timezone.utc).isoformat()}] Starting files-on-demand mount\n"
            f"Command={' '.join(self.mount_command(job))}\n"
        )
        log_handle.flush()
        try:
            process = subprocess.Popen(
                self.mount_command(job),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            log_handle.close()
            return JobResult(job.id, False, str(exc), log_path)
        log_handle.close()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return JobResult(job.id, False, self._mount_failure_summary(log_path), log_path)
            if os.path.ismount(job.local):
                with self._lock:
                    self._mounts[job.id] = process
                    self._mount_paths[job.id] = job.local
                return JobResult(
                    job.id,
                    True,
                    "Files-on-demand drive connected; content streams when a file is opened",
                    log_path,
                )
            time.sleep(0.1)
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        return JobResult(
            job.id,
            False,
            f"Streaming drive did not become available within 45 seconds: {self._mount_failure_summary(log_path)}",
            log_path,
        )

    @staticmethod
    def _mount_failure_summary(log_path: Path) -> str:
        try:
            lines = [line.strip() for line in log_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines() if line.strip()]
        except OSError:
            lines = []
        errors = [
            line for line in lines
            if any(marker in line.lower() for marker in ("error", "fatal", "failed", "fuse", "mount"))
        ]
        detail = (errors or lines or ["rclone exited before mounting the folder"])[-1]
        return f"Streaming drive could not start: {detail[:350]}"

    @staticmethod
    def _unmount_path(path: Path) -> bool:
        if platform.system() == "Darwin":
            unmount = shutil.which("umount")
            if not unmount:
                return False
            result = subprocess.run(
                [unmount, str(path)], check=False, capture_output=True, text=True
            )
            return result.returncode == 0
        unmount = shutil.which("fusermount3") or shutil.which("fusermount")
        if not unmount:
            return False
        result = subprocess.run(
            [unmount, "-uz", str(path)], check=False, capture_output=True, text=True
        )
        return result.returncode == 0

    def stop_mount(self, job: SyncJob) -> bool:
        stopped_process = False
        with self._lock:
            process = self._mounts.pop(job.id, None)
            self._mount_paths.pop(job.id, None)
            if process and process.poll() is None:
                self._intentional_unmounts.add(job.id)
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
                stopped_process = True
            except (ProcessLookupError, subprocess.TimeoutExpired):
                process.kill()
                stopped_process = True
        return self._unmount_path(job.local) or stopped_process

    def recover_stale_mounts(self, jobs: list[SyncJob]) -> list[str]:
        """Lazily detach configured streaming mounts not owned by this process."""
        recovered: list[str] = []
        with self._lock:
            tracked = {
                job_id for job_id, process in self._mounts.items()
                if process.poll() is None
            }
        for job in jobs:
            if job.mode is not SyncMode.VIRTUAL_DRIVE or job.id in tracked:
                continue
            try:
                mounted = os.path.ismount(job.local)
            except OSError:
                mounted = True
            if not mounted:
                try:
                    job.local.stat()
                except OSError as exc:
                    mounted = exc.errno == errno.ENOTCONN
            if mounted and self._unmount_path(job.local):
                recovered.append(job.id)
        return recovered

    def _watch_mount(
        self,
        job: SyncJob,
        process: subprocess.Popen[str],
        log_path: Path,
        callback: Callable[[JobResult], None],
    ) -> None:
        return_code = process.wait()
        with self._lock:
            if self._mounts.get(job.id) is process:
                self._mounts.pop(job.id, None)
                self._mount_paths.pop(job.id, None)
            intentional = job.id in self._intentional_unmounts
            self._intentional_unmounts.discard(job.id)
        if not intentional:
            # rclone/FUSE can leave the kernel mount entry behind after an
            # abrupt exit. Detach it immediately so parent folders remain
            # browsable in Nautilus while the controller schedules a retry.
            self._unmount_path(job.local)
            callback(
                JobResult(
                    job.id,
                    False,
                    f"Files-on-demand drive disconnected unexpectedly (rclone exit {return_code}); "
                    "TuxDrive will retry automatically",
                    log_path,
                    mount_lost=True,
                )
            )

    def shutdown(self) -> None:
        with self._lock:
            job_ids = list(self._processes)
            mounted = [
                (job_id, process, self._mount_paths.get(job_id))
                for job_id, process in self._mounts.items()
            ]
        for job_id in job_ids:
            self.cancel(job_id)
        for monitor in list(self._monitors.values()):
            monitor.stop()
        for job_id, process, path in mounted:
            if process.poll() is None:
                try:
                    with self._lock:
                        self._intentional_unmounts.add(job_id)
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if path is not None:
                self._unmount_path(path)

    def start_callbacks(
        self,
        job: SyncJob,
        callback: Callable[[JobResult], None],
        reconcile: Callable[[SyncJob], None],
    ) -> None:
        if job.is_git or job.mode is SyncMode.VIRTUAL_DRIVE or not job.realtime_sync or not job.initialized:
            return
        self.stop_callbacks(job.id)
        monitor = ChangeMonitor(
            job,
            lambda: self.rclone_path,
            lambda item, changes: self._apply_incremental(item, changes, callback),
            reconcile,
            self._protected_patterns.get(job.id, ()),
        )
        self._monitors[job.id] = monitor
        monitor.start()

    def stop_callbacks(self, job_id: str) -> None:
        monitor = self._monitors.pop(job_id, None)
        if monitor:
            monitor.stop()

    def _incremental_command(self, job: SyncJob, change: FileChange) -> list[str] | None:
        relative = change.path.strip("/")
        if not relative or ".." in Path(relative).parts:
            raise RuntimeError(f"unsafe incremental path: {change.path}")
        if is_transient_path(relative):
            return None
        if change.side == "local" and job.peer_role in {PeerRole.READ_ONLY, PeerRole.RECEIVE_ONLY}:
            return None
        if change.side == "remote" and job.peer_role is PeerRole.SEND_ONLY:
            return None
        # Execution performs a descriptor-based confinement check immediately
        # before touching this path; keep command construction side-effect free.
        local = str(job.local / relative)
        remote = f"{job.remote_spec.rstrip('/')}/{relative}"
        if change.side == "local":
            if change.deleted:
                return [self.rclone_path, "deletefile", remote]
            return [self.rclone_path, "copyto", local, remote]
        if change.deleted:
            return None
        return [self.rclone_path, "copyto", remote, local]

    def _apply_incremental(
        self,
        job: SyncJob,
        changes: list[FileChange],
        callback: Callable[[JobResult], None],
    ) -> bool:
        with self._lock:
            if job.id in self._processes:
                return False
        log_path = self._log_path(job)
        ensure_private_directory(log_path.parent)
        completed = 0
        try:
            total_files = sum(1 for item in job.local.rglob("*") if item.is_file())
            decision = MassChangeGuard.assess(job, changes, total_files)
            if decision.blocked:
                callback(JobResult(
                    job.id, False,
                    f"Protection paused synchronization: {decision.reason}",
                    log_path, incremental=True, mass_change_blocked=True,
                ))
                return False
            self.recovery.archive_incoming_changes(job, changes)
            prepare_private_file(log_path)
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n[{datetime.now(timezone.utc).isoformat()}] Incremental callback: {len(changes)} path(s)\n")
                for change in changes:
                    if ".." in Path(change.path).parts:
                        raise RuntimeError(f"unsafe incremental path: {change.path}")
                    local_path = confined_path(job.local, change.path, create_parents=change.side == "remote")
                    lease = None
                    if job.peer_leases and change.side == "local":
                        try:
                            lease = self.leases.acquire(job, change.path)
                            log.write(f"Edit lease acquired: {change.path}\n")
                        except PeerError as exc:
                            callback(JobResult(job.id, False, f"Edit lease blocked synchronization: {exc}", log_path, incremental=True, lease_blocked=True))
                            return False
                    if change.side == "remote" and change.deleted:
                        try:
                            unlink_confined(job.local, change.path)
                            completed += 1
                        except OSError as exc:
                            raise RuntimeError(str(exc)) from exc
                        continue
                    command = self._incremental_command(job, change)
                    if command is None:
                        if lease:
                            self.leases.release(job, lease)
                        continue
                    if change.side == "local" and not change.deleted and not local_path.exists():
                        log.write(f"Skipped vanished temporary save: {change.path}\n")
                        if lease:
                            self.leases.release(job, lease)
                        continue
                    if (
                        job.block_delta_transfer and job.peer_delta
                        and change.side == "local" and not change.deleted
                    ):
                        if self.transfer_peer_delta(job, change.path, log):
                            completed += 1
                            if lease:
                                self.leases.release(job, lease)
                                log.write(f"Edit lease released: {change.path}\n")
                            continue
                        log.write(f"Authenticated block delta unavailable; using full transfer for {change.path}\n")
                    staged_download = None
                    if change.side == "remote":
                        staging = ensure_private_directory(cache_home() / "tuxdrive" / "incoming" / job.id)
                        staged_download = staging / f"{uuid.uuid4().hex}.download"
                        command[-1] = str(staged_download)
                    try:
                        process = subprocess.Popen(
                            command,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            text=True,
                            start_new_session=True,
                        )
                        with self._lock:
                            self._processes[job.id] = process
                        code = process.wait()
                    finally:
                        if lease:
                            self.leases.release(job, lease)
                            log.write(f"Edit lease released: {change.path}\n")
                    if code:
                        if (
                            change.side == "local"
                            and not change.deleted
                            and not local_path.exists()
                        ):
                            log.write(f"Ignored save artifact that vanished during transfer: {change.path}\n")
                            continue
                        raise RuntimeError(f"incremental transfer failed for {change.path} (rclone exit {code})")
                    if staged_download is not None:
                        install_confined(staged_download, job.local, change.path)
                        staged_download.unlink(missing_ok=True)
                    completed += 1
            callback(JobResult(job.id, True, f"Incremental sync complete: {completed} changed path(s)", log_path, incremental=True))
            return True
        except (OSError, RuntimeError, UnsafePathError) as exc:
            callback(JobResult(job.id, False, f"Incremental sync failed: {exc}", log_path, incremental=True))
            return False
        finally:
            with self._lock:
                self._processes.pop(job.id, None)

    def _run_worker(
        self,
        job: SyncJob,
        log_path: Path,
        callback: Callable[[JobResult], None],
        dry_run: bool,
    ) -> None:
        if job.is_git:
            callback(self._run_git_sync(job, log_path, dry_run))
            return
        ensure_private_directory(log_path.parent)
        cancelled = False
        try:
            resolved = resolve_rclone(self.rclone_path)
            if resolved is None:
                resolved = install_rclone()
            self.rclone_path = resolved
            self.leases.rclone_path = resolved
            if job.peer_leases and not dry_run:
                active = self.leases.foreign_leases(job)
                if active:
                    detail = ", ".join(f"{item.path} ({item.owner})" for item in active[:5])
                    callback(JobResult(job.id, False, f"Synchronization paused for active peer edit lease(s): {detail}", log_path, lease_blocked=True))
                    return
            if job.ransomware_protection and job.initialized and not dry_run:
                preview_path = log_path.with_name(log_path.stem + "-safety-preview.log")
                preview_command = self.command_for_job(job, dry_run=True)
                with preview_path.open("w", encoding="utf-8") as preview:
                    preview_process = subprocess.run(
                        preview_command, stdout=preview, stderr=subprocess.STDOUT,
                        text=True, timeout=3600, check=False,
                    )
                if preview_process.returncode != 0:
                    raise RuntimeError("the safety preview could not be completed; the real sync was not started")
                total_files = sum(1 for item in job.local.rglob("*") if item.is_file())
                decision = MassChangeGuard.assess_log(job, preview_path, total_files)
                if decision.blocked:
                    callback(JobResult(
                        job.id, False,
                        f"Protection paused synchronization: {decision.reason}",
                        preview_path, mass_change_blocked=True,
                    ))
                    return
            command = self.command_for_job(job, dry_run=dry_run)
            prepare_private_file(log_path)
            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    f"\n[{datetime.now(timezone.utc).isoformat()}] Starting TuxDrive "
                    f"{__version__} sync with {self.rclone_path}\n"
                )
                process = subprocess.Popen(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                with self._lock:
                    self._processes[job.id] = process
                return_code = process.wait()
                cancelled = return_code in (-signal.SIGTERM, 143)
                log.write(f"[{datetime.now(timezone.utc).isoformat()}] Exit {return_code}\n")
            if return_code == 0:
                result = JobResult(job.id, True, "Synchronization complete", log_path)
            elif cancelled:
                result = JobResult(job.id, False, "Synchronization cancelled", log_path, True)
            else:
                requires_resync = self._requires_resync(log_path)
                blocked_path = self._blocked_google_path(log_path)
                result = JobResult(
                    job.id,
                    False,
                    self._failure_summary(log_path, return_code),
                    log_path,
                    requires_resync=requires_resync,
                    blocked_path=blocked_path,
                )
        except (OSError, RuntimeError) as exc:
            result = JobResult(job.id, False, f"Synchronization could not start: {exc}", log_path)
        finally:
            with self._lock:
                self._processes.pop(job.id, None)
        callback(result)

    def _run_git_sync(self, job: SyncJob, log_path: Path, dry_run: bool) -> JobResult:
        """Synchronize a GitHub working tree without storing access tokens."""
        ensure_private_directory(log_path.parent)
        prepare_private_file(log_path)
        try:
            repository = parse_repository_url(job.repository_url)
            branch = validate_branch(job.repository_branch)
            git = shutil.which("git")
            if not git:
                raise GitHubSyncError("Git is not installed")
            environment = os.environ.copy()
            environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false"})

            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    f"\n[{datetime.now(timezone.utc).isoformat()}] Starting GitHub "
                    f"synchronization for {repository.owner}/{repository.name} ({branch})\n"
                )
                if dry_run:
                    return JobResult(job.id, True, "GitHub synchronization preview complete", log_path)

                metadata = job.local / ".git"
                if not metadata.exists():
                    if any(job.local.iterdir()):
                        raise GitHubSyncError(
                            "The selected local folder is not empty and is not a Git repository"
                        )
                    code = self._run_git_process(
                        job,
                        [git, "clone", "--single-branch", "--branch", branch, job.repository_url, str(job.local)],
                        job.local.parent,
                        log,
                        environment,
                    )
                    if code:
                        return self._git_failure(job, log_path, code, "clone")
                else:
                    origin = self._git_output(
                        [git, "-C", str(job.local), "remote", "get-url", "origin"], environment
                    )
                    current = parse_repository_url(origin)
                    if (current.owner.lower(), current.name.lower()) != (
                        repository.owner.lower(), repository.name.lower()
                    ):
                        raise GitHubSyncError(
                            "The local folder's origin points to a different GitHub repository"
                        )
                    current_branch = self._git_output(
                        [git, "-C", str(job.local), "branch", "--show-current"], environment
                    )
                    if current_branch != branch:
                        raise GitHubSyncError(
                            f"The local repository is on branch '{current_branch or 'detached HEAD'}', not '{branch}'"
                        )

                if job.git_author_name:
                    self._run_git_process(
                        job,
                        [git, "-C", str(job.local), "config", "user.name", job.git_author_name],
                        job.local,
                        log,
                        environment,
                    )
                if job.git_author_email:
                    self._run_git_process(
                        job,
                        [git, "-C", str(job.local), "config", "user.email", job.git_author_email],
                        job.local,
                        log,
                        environment,
                    )

                if job.mode is SyncMode.DOWNLOAD_ONLY:
                    if self._git_dirty(git, job.local, environment):
                        raise GitHubSyncError(
                            "Download-only synchronization stopped because the local repository has uncommitted changes"
                        )
                    if self._run_git_process(
                        job, [git, "-C", str(job.local), "fetch", "origin", branch],
                        job.local, log, environment,
                    ):
                        return self._git_failure(job, log_path, 1, "fetch")
                    code = self._run_git_process(
                        job, [git, "-C", str(job.local), "merge", "--ff-only", f"origin/{branch}"],
                        job.local, log, environment,
                    )
                    return (
                        self._git_failure(job, log_path, code, "fast-forward")
                        if code else JobResult(job.id, True, "GitHub download complete", log_path)
                    )

                changes = self._git_changes(git, job.local, environment)
                if job.ransomware_protection and job.initialized and changes:
                    total_files = sum(
                        1 for item in job.local.rglob("*")
                        if item.is_file() and ".git" not in item.relative_to(job.local).parts
                    )
                    decision = MassChangeGuard.assess(job, changes, total_files)
                    if decision.blocked:
                        return JobResult(
                            job.id, False,
                            f"Protection paused GitHub synchronization: {decision.reason}",
                            log_path, mass_change_blocked=True,
                        )
                deleted = sum(1 for item in changes if item.deleted)
                if job.max_delete >= 0 and deleted > job.max_delete:
                    return JobResult(
                        job.id, False,
                        f"Protection paused GitHub synchronization: {deleted} local deletions exceed the limit of {job.max_delete}",
                        log_path, mass_change_blocked=True,
                    )
                if self._run_git_process(
                    job, [git, "-C", str(job.local), "add", "-A"],
                    job.local, log, environment,
                ):
                    return self._git_failure(job, log_path, 1, "stage")
                staged = subprocess.run(
                    [git, "-C", str(job.local), "diff", "--cached", "--quiet"],
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode != 0
                if staged:
                    message = f"TuxDrive sync {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    code = self._run_git_process(
                        job, [git, "-C", str(job.local), "commit", "-m", message],
                        job.local, log, environment,
                    )
                    if code:
                        return self._git_failure(
                            job, log_path, code, "commit (check Git author name and email)"
                        )
                if self._run_git_process(
                    job, [git, "-C", str(job.local), "fetch", "origin", branch],
                    job.local, log, environment,
                ):
                    return self._git_failure(job, log_path, 1, "fetch")
                if job.mode is SyncMode.TWO_WAY:
                    code = self._run_git_process(
                        job, [git, "-C", str(job.local), "rebase", f"origin/{branch}"],
                        job.local, log, environment,
                    )
                    if code:
                        self._run_git_process(
                            job, [git, "-C", str(job.local), "rebase", "--abort"],
                            job.local, log, environment,
                        )
                        return JobResult(
                            job.id, False,
                            "GitHub synchronization stopped on a rebase conflict; local changes were restored",
                            log_path,
                        )
                else:
                    code = self._run_git_process(
                        job,
                        [git, "-C", str(job.local), "merge-base", "--is-ancestor", f"origin/{branch}", "HEAD"],
                        job.local, log, environment,
                    )
                    if code:
                        return JobResult(
                            job.id, False,
                            "Upload-only synchronization stopped because GitHub contains changes not present locally",
                            log_path,
                        )
                code = self._run_git_process(
                    job, [git, "-C", str(job.local), "push", "origin", f"HEAD:{branch}"],
                    job.local, log, environment,
                )
                return (
                    self._git_failure(job, log_path, code, "push")
                    if code else JobResult(job.id, True, "GitHub synchronization complete", log_path)
                )
        except (OSError, RuntimeError, GitHubSyncError) as exc:
            return JobResult(job.id, False, f"GitHub synchronization could not start: {exc}", log_path)
        finally:
            with self._lock:
                self._processes.pop(job.id, None)

    def _run_git_process(
        self, job: SyncJob, command: list[str], cwd: Path, log, environment: dict[str, str]
    ) -> int:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        with self._lock:
            self._processes[job.id] = process
        return process.wait()

    @staticmethod
    def _git_output(command: list[str], environment: dict[str, str]) -> str:
        result = subprocess.run(
            command, env=environment, capture_output=True, text=True, timeout=60, check=False
        )
        if result.returncode:
            raise GitHubSyncError(
                (result.stderr or result.stdout or "Git command failed").strip()
            )
        return result.stdout.strip()

    @staticmethod
    def _git_dirty(git: str, folder: Path, environment: dict[str, str]) -> bool:
        result = subprocess.run(
            [git, "-C", str(folder), "status", "--porcelain"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise GitHubSyncError(
                (result.stderr or "Could not inspect the local repository").strip()
            )
        return bool(result.stdout.strip())

    @staticmethod
    def _git_changes(git: str, folder: Path, environment: dict[str, str]) -> list[FileChange]:
        result = subprocess.run(
            [git, "-C", str(folder), "status", "--porcelain", "--untracked-files=all"],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise GitHubSyncError(
                (result.stderr or "Could not inspect local GitHub changes").strip()
            )
        changes: list[FileChange] = []
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            status, path = line[:2], line[3:]
            if " -> " in path:
                path = path.rsplit(" -> ", 1)[1]
            changes.append(FileChange(path.strip('"'), "local", "D" in status))
        return changes

    @staticmethod
    def _git_failure(job: SyncJob, log_path: Path, code: int, action: str) -> JobResult:
        cancelled = code in (-signal.SIGTERM, 143)
        return JobResult(
            job.id,
            False,
            "GitHub synchronization cancelled"
            if cancelled else
            f"GitHub {action} failed; see the job log. Configure SSH or a system Git credential helper for private/write access.",
            log_path,
            cancelled=cancelled,
        )

    @staticmethod
    def _conflict_flags(policy: ConflictPolicy) -> list[str]:
        if policy is ConflictPolicy.NEWER_WINS:
            return ["--conflict-resolve", "newer"]
        if policy is ConflictPolicy.LOCAL_WINS:
            return ["--conflict-resolve", "path1"]
        if policy is ConflictPolicy.CLOUD_WINS:
            return ["--conflict-resolve", "path2"]
        return ["--conflict-resolve", "none"]

    @staticmethod
    def _failure_summary(log_path: Path, return_code: int) -> str:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        cleaned_lines = [ansi.sub("", line).strip() for line in lines[-2000:]]
        abusive = next(
            (line for line in reversed(cleaned_lines) if "cannotDownloadAbusiveFile" in line),
            None,
        )
        if abusive:
            match = re.search(r"(?:ERROR\s+:\s+)?(.+?): Failed to copy", abusive)
            blocked = match.group(1) if match else "a file"
            return (
                f"Google blocked {blocked} as suspected malware or spam. "
                "Exclude it, or edit this job and explicitly allow flagged downloads."
            )[:500]
        for cleaned in reversed(cleaned_lines):
            lowered = cleaned.lower()
            if lowered.startswith(("fatal error:", "bisync critical error:")):
                detail = cleaned.split(":", 1)[1].strip()
                return f"Synchronization failed: {detail[:300]}"
        return f"Synchronization failed (rclone exit {return_code}); see log"

    @staticmethod
    def _blocked_google_path(log_path: Path) -> str:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        ansi = re.compile(r"\x1b\[[0-9;]*m")
        for line in reversed(lines[-2000:]):
            cleaned = ansi.sub("", line).strip()
            if "cannotDownloadAbusiveFile" not in cleaned:
                continue
            match = re.search(r"(?:ERROR\s+:\s+)?(.+?): Failed to copy", cleaned)
            if match:
                return match.group(1).strip()
        return ""

    @staticmethod
    def _requires_resync(log_path: Path) -> bool:
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-64 * 1024 :]
        except OSError:
            return False
        return "Must run --resync to recover" in tail

    @staticmethod
    def _log_path(job: SyncJob) -> Path:
        stamp = datetime.now().strftime("%Y%m%d")
        return cache_home() / "tuxdrive" / "logs" / f"{job.id}-{stamp}.log"
