from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import SyncJob, SyncMode


@dataclass(frozen=True, slots=True)
class FileState:
    size: int
    modified: str


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    side: str
    deleted: bool = False


def changes_between(
    previous: dict[str, FileState], current: dict[str, FileState], side: str
) -> list[FileChange]:
    changed = [
        FileChange(path, side, path not in current)
        for path in sorted(previous.keys() | current.keys())
        if previous.get(path) != current.get(path)
    ]
    return changed


class ChangeMonitor:
    """Debounced local-save callbacks plus provider-side delta polling."""

    def __init__(
        self,
        job: SyncJob,
        rclone_path: Callable[[], str],
        apply: Callable[[SyncJob, list[FileChange]], bool],
        reconcile: Callable[[SyncJob], None],
        local_poll_seconds: float = 2.0,
        remote_poll_seconds: float = 30.0,
    ) -> None:
        self.job = job
        self.rclone_path = rclone_path
        self.apply = apply
        self.reconcile = reconcile
        self.local_poll_seconds = local_poll_seconds
        self.remote_poll_seconds = remote_poll_seconds
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run, name=f"tuxdrive-callback-{job.id[:8]}", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _excluded(self, relative: str) -> bool:
        candidate = relative.replace(os.sep, "/")
        return any(
            fnmatch.fnmatch(candidate, pattern.lstrip("/"))
            or fnmatch.fnmatch("/" + candidate, pattern)
            for pattern in self.job.exclude_patterns
            if pattern.strip()
        )

    def local_snapshot(self) -> dict[str, FileState]:
        result: dict[str, FileState] = {}
        if not self.job.local.exists():
            return result
        for root, _dirs, files in os.walk(self.job.local):
            for filename in files:
                path = Path(root) / filename
                relative = path.relative_to(self.job.local).as_posix()
                if self._excluded(relative):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                result[relative] = FileState(stat.st_size, str(stat.st_mtime_ns))
        return result

    def remote_snapshot(self) -> dict[str, FileState]:
        process = subprocess.run(
            [
                self.rclone_path(),
                "lsjson",
                self.job.remote_spec,
                "--recursive",
                "--files-only",
                "--no-mimetype",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or "Cloud change scan failed")
        values = json.loads(process.stdout or "[]")
        return {
            item["Path"]: FileState(int(item.get("Size", -1)), item.get("ModTime", ""))
            for item in values
            if item.get("Path") and not self._excluded(item["Path"])
        }

    def _run(self) -> None:
        try:
            local = self.local_snapshot()
            remote = self.remote_snapshot()
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            return
        last_remote_scan = time.monotonic()
        while not self.stop_event.wait(self.local_poll_seconds):
            if not self.job.enabled or not self.job.realtime_sync:
                continue
            new_local = self.local_snapshot()
            local_changes = changes_between(local, new_local, "local")
            remote_due = time.monotonic() - last_remote_scan >= self.remote_poll_seconds
            if not local_changes and not remote_due:
                continue
            try:
                new_remote = self.remote_snapshot()
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                continue
            last_remote_scan = time.monotonic()
            remote_changes = changes_between(remote, new_remote, "remote")
            local_paths = {change.path for change in local_changes}
            remote_paths = {change.path for change in remote_changes}
            if local_paths & remote_paths and self.job.mode is SyncMode.TWO_WAY:
                self.reconcile(self.job)
            else:
                permitted = [
                    change
                    for change in local_changes + remote_changes
                    if not (
                        change.side == "local" and self.job.mode is SyncMode.DOWNLOAD_ONLY
                    )
                    and not (
                        change.side == "remote" and self.job.mode is SyncMode.UPLOAD_ONLY
                    )
                ]
                if permitted:
                    self.apply(self.job, permitted)
            # Rescan after transfers to absorb their mirror-side events and prevent loops.
            try:
                local = self.local_snapshot()
                remote = self.remote_snapshot()
                last_remote_scan = time.monotonic()
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                local, remote = new_local, new_remote

