from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .bootstrap import install_rclone, resolve_rclone
from .callbacks import ChangeMonitor, FileChange
from .config import cache_home
from .models import ConflictPolicy, SyncJob, SyncMode


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


class SyncEngine:
    def __init__(self, rclone_path: str = "rclone") -> None:
        self.rclone_path = rclone_path
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._mounts: dict[str, subprocess.Popen[str]] = {}
        self._monitors: dict[str, ChangeMonitor] = {}
        self._lock = threading.RLock()

    @property
    def running_jobs(self) -> set[str]:
        with self._lock:
            return set(self._processes)

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
        for pattern in job.exclude_patterns:
            if pattern.strip():
                common.extend(["--exclude", pattern.strip()])
        if job.bandwidth_limit.strip():
            common.extend(["--bwlimit", job.bandwidth_limit.strip()])
        if dry_run:
            common.append("--dry-run")

        if job.mode is SyncMode.TWO_WAY:
            command = [self.rclone_path, "bisync", local, job.remote_spec]
            command.extend(["--resilient", "--recover", "--conflict-loser", "pathname"])
            command.extend(self._conflict_flags(job.conflict_policy))
            workdir = cache_home() / "tuxdrive" / "bisync" / job.id
            command.extend(["--workdir", str(workdir)])
            if not job.initialized:
                command.extend(["--resync", "--resync-mode", "newer"])
            return [*command, *common]

        if job.mode is SyncMode.DOWNLOAD_ONLY:
            return [self.rclone_path, "sync", job.remote_spec, local, *common]
        if job.mode is SyncMode.UPLOAD_ONLY:
            return [self.rclone_path, "sync", local, job.remote_spec, *common]
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            return self.mount_command(job)
        raise ValueError(f"Unsupported sync mode: {job.mode}")

    def mount_command(self, job: SyncJob) -> list[str]:
        cache = cache_home() / "tuxdrive" / "vfs" / job.id
        return [
            self.rclone_path,
            "mount",
            job.remote_spec,
            str(job.local),
            "--vfs-cache-mode",
            "full",
            "--vfs-cache-max-age",
            "24h",
            "--vfs-cache-poll-interval",
            "1m",
            "--cache-dir",
            str(cache),
            "--dir-cache-time",
            "5m",
            "--poll-interval",
            "30s",
            "--umask",
            "022",
        ]

    def run_async(
        self,
        job: SyncJob,
        callback: Callable[[JobResult], None],
        dry_run: bool = False,
    ) -> bool:
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            result = self.start_mount(job)
            callback(result)
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
        job.local.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")
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
        try:
            process.wait(timeout=0.8)
        except subprocess.TimeoutExpired:
            with self._lock:
                self._mounts[job.id] = process
            return JobResult(job.id, True, "Virtual drive mounted", log_path)
        return JobResult(job.id, False, "Virtual drive exited during startup; see log", log_path)

    def stop_mount(self, job: SyncJob) -> bool:
        with self._lock:
            process = self._mounts.pop(job.id, None)
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
                return True
            except (ProcessLookupError, subprocess.TimeoutExpired):
                process.kill()
        unmount = shutil.which("fusermount3") or shutil.which("fusermount")
        if unmount:
            subprocess.run([unmount, "-u", str(job.local)], check=False, capture_output=True)
            return True
        return False

    def shutdown(self) -> None:
        with self._lock:
            job_ids = list(self._processes)
            mounted = list(self._mounts.items())
        for job_id in job_ids:
            self.cancel(job_id)
        for monitor in list(self._monitors.values()):
            monitor.stop()
        for _, process in mounted:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

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
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n[{datetime.now(timezone.utc).isoformat()}] Incremental callback: {len(changes)} path(s)\n")
                for change in changes:
                    if ".." in Path(change.path).parts:
                        raise RuntimeError(f"unsafe incremental path: {change.path}")
                    local_path = job.local / change.path
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
                        continue
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
                    if code:
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
