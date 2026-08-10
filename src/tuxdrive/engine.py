from __future__ import annotations

import errno
import os
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
from .config import cache_home
from .models import ConflictPolicy, SyncJob, SyncMode
from .recovery import MassChangeGuard, RecoveryManager
from .peer import PeerError, PeerLeaseManager
from .delta import BlockDeltaPlanner, BlockSignature


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
            return [self.rclone_path, "sync", job.remote_spec, local, *history, *common]
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
            # Pinned content is hydrated into the VFS cache and must not age
            # out. Size pressure remains visible to the user through the
            # explicit Free local space action.
            index = command.index("--vfs-cache-max-age")
            command[index + 1] = "87600h"
        return command

    def set_offline(self, job: SyncJob, relative: str, available: bool) -> str:
        relative = relative.strip("/")
        if not relative or relative.startswith("../"):
            raise ValueError("Select a file or folder inside the streaming drive")
        if available:
            if relative not in job.offline_paths:
                job.offline_paths.append(relative)
            target = job.local / relative
            if target.is_file():
                with target.open("rb") as handle:
                    while handle.read(4 * 1024 * 1024):
                        pass
            elif target.is_dir():
                for item in target.rglob("*"):
                    if item.is_file():
                        with item.open("rb") as handle:
                            while handle.read(4 * 1024 * 1024):
                                pass
            return "Available offline"
        if relative == ".":
            job.offline_paths.clear()
        else:
            job.offline_paths = [item for item in job.offline_paths if item != relative and not item.startswith(relative + "/")]
        cache = cache_home() / "tuxdrive" / "vfs" / job.id
        if relative == "." and cache.exists():
            shutil.rmtree(cache)
            return "Online only; streaming cache released"
        suffix = "/" + relative
        for item in (cache.rglob("*") if cache.exists() else ()):
            if item.is_file() and item.as_posix().endswith(suffix):
                item.unlink(missing_ok=True)
        return "Online only; matching cached content released"

    def record_delta_manifest(self, job: SyncJob, relative: str) -> tuple[int, int]:
        """Persist rolling-block signatures and report changed/total bytes."""
        source = job.local / relative
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
        source = job.local / relative
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
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as diagnostic:
            diagnostic.write(
                f"\n[{datetime.now(timezone.utc).isoformat()}] Streaming preflight\n"
                f"TuxDrive={__version__}\nRemote={job.remote_spec}\nMountPoint={job.local}\n"
                f"Rclone={self.rclone_path}\nFuseDevice={Path('/dev/fuse').exists()}\n"
                f"Fusermount={shutil.which('fusermount3') or shutil.which('fusermount') or 'missing'}\n"
            )
        if not Path("/dev/fuse").exists():
            return JobResult(
                job.id, False,
                "Streaming requires /dev/fuse, but the FUSE device is unavailable. See the job log.",
                log_path,
            )
        if not (shutil.which("fusermount3") or shutil.which("fusermount")):
            return JobResult(
                job.id, False,
                "Streaming requires fusermount3, but it is unavailable. Reinstall the TuxDrive package.",
                log_path,
            )
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
        if job.mode is SyncMode.VIRTUAL_DRIVE or not job.realtime_sync or not job.initialized:
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
        log_path.parent.mkdir(parents=True, exist_ok=True)
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
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n[{datetime.now(timezone.utc).isoformat()}] Incremental callback: {len(changes)} path(s)\n")
                for change in changes:
                    if ".." in Path(change.path).parts:
                        raise RuntimeError(f"unsafe incremental path: {change.path}")
                    local_path = job.local / change.path
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
                            local_path.unlink(missing_ok=True)
                            completed += 1
                        except OSError as exc:
                            raise RuntimeError(str(exc)) from exc
                        continue
                    if change.side == "remote":
                        local_path.parent.mkdir(parents=True, exist_ok=True)
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
                        if not self.transfer_peer_delta(job, change.path, log):
                            raise RuntimeError(f"block delta transfer failed for {change.path}")
                        completed += 1
                        if lease:
                            self.leases.release(job, lease)
                            log.write(f"Edit lease released: {change.path}\n")
                        continue
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
                    completed += 1
            callback(JobResult(job.id, True, f"Incremental sync complete: {completed} changed path(s)", log_path, incremental=True))
            return True
        except (OSError, RuntimeError) as exc:
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
        log_path.parent.mkdir(parents=True, exist_ok=True)
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
