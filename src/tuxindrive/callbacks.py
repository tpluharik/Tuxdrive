from __future__ import annotations

import ctypes
import errno
import fnmatch
import json
import os
import platform
import selectors
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .models import SyncJob, SyncMode


TRANSIENT_PATTERNS = (
    ".~lock.*#", "~$*", ".goutputstream-*", ".nfs*", "*.part",
    "*.partial", "*.crdownload", "*.swp", "*.swx", "*~",
)


def is_transient_path(relative: str) -> bool:
    return any(
        fnmatch.fnmatch(part, pattern)
        for part in Path(relative).parts
        for pattern in TRANSIENT_PATTERNS
    )


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
    return [
        FileChange(path, side, path not in current)
        for path in sorted(previous.keys() | current.keys())
        if previous.get(path) != current.get(path)
    ]


@dataclass(frozen=True, slots=True)
class LocalEvents:
    paths: frozenset[str] = frozenset()
    overflow: bool = False
    rescan: bool = False


class InotifyTreeMonitor:
    """Bounded kernel-backed recursive monitor.

    The kernel queue is the bound. IN_Q_OVERFLOW is surfaced explicitly so
    callers can fail closed into a full reconciliation instead of losing a
    change silently. Directory topology changes request a local rescan because
    a single rename event cannot safely describe every descendant.
    """

    _EVENT = struct.Struct("iIII")
    _NONBLOCK = getattr(os, "O_NONBLOCK", 0x800)
    _CLOEXEC = getattr(os, "O_CLOEXEC", 0x80000)
    _MODIFY = 0x00000002
    _ATTRIB = 0x00000004
    _CLOSE_WRITE = 0x00000008
    _MOVED_FROM = 0x00000040
    _MOVED_TO = 0x00000080
    _CREATE = 0x00000100
    _DELETE = 0x00000200
    _DELETE_SELF = 0x00000400
    _MOVE_SELF = 0x00000800
    _Q_OVERFLOW = 0x00004000
    _IGNORED = 0x00008000
    _ONLYDIR = 0x01000000
    _DONT_FOLLOW = 0x02000000
    _ISDIR = 0x40000000
    _WATCH_MASK = (
        _MODIFY | _ATTRIB | _CLOSE_WRITE | _MOVED_FROM | _MOVED_TO |
        _CREATE | _DELETE | _DELETE_SELF | _MOVE_SELF
    )

    def __init__(self, root: Path, excluded: Callable[[str], bool]) -> None:
        if platform.system() != "Linux":
            raise OSError(errno.ENOSYS, "inotify is available only on Linux")
        libc = ctypes.CDLL(None, use_errno=True)
        init = libc.inotify_init1
        init.argtypes = [ctypes.c_int]
        init.restype = ctypes.c_int
        self._add = libc.inotify_add_watch
        self._add.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._add.restype = ctypes.c_int
        self.fd = init(self._NONBLOCK | self._CLOEXEC)
        if self.fd < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        self.root = root.resolve(strict=False)
        self.excluded = excluded
        self._watches: dict[int, Path] = {}
        self._selector = selectors.DefaultSelector()
        self._selector.register(self.fd, selectors.EVENT_READ)
        try:
            self._watch_tree(self.root)
        except Exception:
            self.close()
            raise

    def _watch(self, directory: Path) -> None:
        descriptor = self._add(
            self.fd, os.fsencode(directory),
            ctypes.c_uint32(self._WATCH_MASK | self._ONLYDIR | self._DONT_FOLLOW),
        )
        if descriptor < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(directory))
        self._watches[descriptor] = directory

    def _watch_tree(self, directory: Path) -> None:
        for root, directories, _files in os.walk(directory, followlinks=False):
            root_path = Path(root)
            kept: list[str] = []
            for name in directories:
                candidate = root_path / name
                try:
                    relative = candidate.relative_to(self.root).as_posix()
                except ValueError:
                    continue
                if not candidate.is_symlink() and not self.excluded(relative):
                    kept.append(name)
            directories[:] = kept
            self._watch(root_path)

    def read(self, timeout: float) -> LocalEvents:
        if not self._selector.select(max(0.0, timeout)):
            return LocalEvents()
        paths: set[str] = set()
        overflow = False
        rescan = False
        while True:
            try:
                data = os.read(self.fd, 256 * 1024)
            except BlockingIOError:
                break
            if not data:
                break
            offset = 0
            while offset + self._EVENT.size <= len(data):
                watch, mask, _cookie, length = self._EVENT.unpack_from(data, offset)
                offset += self._EVENT.size
                raw_name = data[offset:offset + length]
                offset += length
                name = os.fsdecode(raw_name.split(b"\0", 1)[0]) if raw_name else ""
                if mask & self._Q_OVERFLOW:
                    overflow = True
                    continue
                parent = self._watches.get(watch)
                if parent is None:
                    rescan = True
                    continue
                candidate = parent / name if name else parent
                try:
                    relative = candidate.relative_to(self.root).as_posix()
                except ValueError:
                    overflow = True
                    continue
                if relative == "." or self.excluded(relative):
                    continue
                if mask & self._ISDIR:
                    rescan = True
                    if mask & (self._CREATE | self._MOVED_TO):
                        try:
                            self._watch_tree(candidate)
                        except OSError:
                            overflow = True
                else:
                    paths.add(relative)
                if mask & (self._DELETE_SELF | self._MOVE_SELF | self._IGNORED):
                    self._watches.pop(watch, None)
                    rescan = True
        return LocalEvents(frozenset(paths), overflow, rescan)

    def close(self) -> None:
        try:
            self._selector.close()
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass


class ChangeMonitor:
    """Event-driven local callbacks plus adaptive provider reconciliation."""

    def __init__(
        self,
        job: SyncJob,
        rclone_path: Callable[[], str],
        apply: Callable[[SyncJob, list[FileChange]], bool],
        reconcile: Callable[[SyncJob], None],
        protected_patterns: tuple[str, ...] = (),
        local_poll_seconds: float = 10.0,
        remote_poll_seconds: float = 30.0,
        remote_backoff: tuple[float, ...] = (30.0, 60.0, 120.0, 300.0),
        event_factory: Callable[[Path, Callable[[str], bool]], InotifyTreeMonitor] = InotifyTreeMonitor,
    ) -> None:
        self.job = job
        self.rclone_path = rclone_path
        self.apply = apply
        self.reconcile = reconcile
        self.protected_patterns = protected_patterns
        self.local_poll_seconds = max(1.0, local_poll_seconds)
        self.remote_poll_seconds = max(1.0, remote_poll_seconds)
        self.remote_backoff = tuple(max(1.0, value) for value in remote_backoff)
        self.event_factory = event_factory
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run, name=f"tuxindrive-callback-{job.id[:8]}", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _excluded(self, relative: str) -> bool:
        candidate = relative.replace(os.sep, "/")
        return is_transient_path(candidate) or any(
            fnmatch.fnmatch(candidate, pattern.lstrip("/"))
            or fnmatch.fnmatch("/" + candidate, pattern)
            for pattern in (*self.job.exclude_patterns, *self.protected_patterns)
            if pattern.strip()
        )

    def _file_state(self, relative: str) -> FileState | None:
        try:
            path = self.job.local / relative
            stat = path.stat(follow_symlinks=False)
            if not path.is_file() or path.is_symlink():
                return None
            return FileState(stat.st_size, str(stat.st_mtime_ns))
        except OSError:
            return None

    def local_snapshot(self) -> dict[str, FileState]:
        result: dict[str, FileState] = {}
        if not self.job.local.exists():
            return result
        for root, directories, files in os.walk(self.job.local, followlinks=False):
            relative_root = os.path.relpath(root, self.job.local)
            directories[:] = [
                directory for directory in directories
                if not os.path.islink(os.path.join(root, directory))
                and not self._excluded(
                    directory if relative_root == "." else f"{relative_root}/{directory}"
                )
            ]
            for filename in files:
                relative = (
                    filename if relative_root == "." else f"{relative_root}/{filename}"
                ).replace(os.sep, "/")
                if self._excluded(relative):
                    continue
                state = self._file_state(relative)
                if state is not None:
                    result[relative] = state
        return result

    def remote_snapshot(self) -> dict[str, FileState]:
        process = subprocess.run(
            [self.rclone_path(), "lsjson", self.job.remote_spec, "--recursive",
             "--files-only", "--no-mimetype"],
            check=False, capture_output=True, text=True, timeout=120,
        )
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or "Cloud change scan failed")
        values = json.loads(process.stdout or "[]")
        if not isinstance(values, list):
            raise ValueError("Cloud change scan returned an invalid object")
        return {
            item["Path"]: FileState(int(item.get("Size", -1)), str(item.get("ModTime", "")))
            for item in values
            if isinstance(item, dict) and item.get("Path")
            and not self._excluded(str(item["Path"]))
        }

    @staticmethod
    def _mirror(snapshot: dict[str, FileState], changes: list[FileChange], source: dict[str, FileState]) -> None:
        for change in changes:
            if change.deleted:
                snapshot.pop(change.path, None)
            elif change.path in source:
                snapshot[change.path] = source[change.path]

    def _run(self) -> None:
        local = self.local_snapshot()
        try:
            events: InotifyTreeMonitor | None = self.event_factory(self.job.local, self._excluded)
        except OSError:
            events = None
        try:
            remote = self.remote_snapshot()
            remote_known = True
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            remote, remote_known = {}, False
        # Close the startup race between the initial snapshot and watch
        # installation/remote baseline. Events remain queued by the kernel,
        # while this second snapshot catches anything changed just before the
        # watches were installed.
        startup_local = self.local_snapshot()
        startup_changes = changes_between(local, startup_local, "local")
        local = startup_local
        deferred_local = {change.path: change for change in startup_changes}
        deferred_remote: dict[str, FileChange] = {}
        last_local_scan = time.monotonic()
        last_remote_scan = time.monotonic()
        backoff_index = 0
        remote_delay = self.remote_backoff[0] if self.remote_backoff else self.remote_poll_seconds
        recovery_due: float | None = None
        try:
            while not self.stop_event.is_set():
                if not self.job.enabled or not self.job.realtime_sync:
                    self.stop_event.wait(1.0)
                    continue
                now = time.monotonic()
                remote_due_at = last_remote_scan + remote_delay
                if recovery_due is not None:
                    remote_due_at = min(remote_due_at, recovery_due)
                timeout = min(1.0, max(0.0, remote_due_at - now))
                local_changes: list[FileChange] = []
                unsafe_monitor = False
                if events is not None and not local_changes:
                    batch = events.read(timeout)
                    if batch.overflow or batch.rescan:
                        new_local = self.local_snapshot()
                        local_changes = changes_between(local, new_local, "local")
                        local = new_local
                        unsafe_monitor = batch.overflow
                    elif batch.paths:
                        before = dict(local)
                        for relative in batch.paths:
                            state = self._file_state(relative)
                            if state is None:
                                local.pop(relative, None)
                            else:
                                local[relative] = state
                        local_changes = changes_between(before, local, "local")
                elif events is None:
                    self.stop_event.wait(timeout)
                    now = time.monotonic()
                    if now - last_local_scan >= self.local_poll_seconds:
                        new_local = self.local_snapshot()
                        local_changes = changes_between(local, new_local, "local")
                        local = new_local
                        last_local_scan = now
                if deferred_local:
                    merged = dict(deferred_local)
                    merged.update({change.path: change for change in local_changes})
                    local_changes = list(merged.values())
                if unsafe_monitor:
                    self.reconcile(self.job)
                    recovery_due = time.monotonic() + 10.0
                    continue
                now = time.monotonic()
                remote_due = bool(local_changes) or now >= last_remote_scan + remote_delay
                if recovery_due is not None and now >= recovery_due:
                    remote_due = True
                if not remote_due:
                    continue
                try:
                    new_remote = self.remote_snapshot()
                except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                    # Network/provider failure must not cause a local full scan.
                    deferred_local.update({change.path: change for change in local_changes})
                    remote_delay = min(
                        300.0, max(remote_delay * 2, self.remote_poll_seconds)
                    )
                    if recovery_due is not None:
                        recovery_due = time.monotonic() + remote_delay
                    continue
                last_remote_scan = time.monotonic()
                baseline_uncertain = not remote_known
                if not remote_known:
                    remote, remote_known = new_remote, True
                    remote_delay = self.remote_backoff[0] if self.remote_backoff else self.remote_poll_seconds
                remote_changes = [] if baseline_uncertain else changes_between(remote, new_remote, "remote")
                if deferred_remote:
                    merged_remote = dict(deferred_remote)
                    merged_remote.update({change.path: change for change in remote_changes})
                    remote_changes = list(merged_remote.values())
                if baseline_uncertain and local_changes and self.job.mode is SyncMode.TWO_WAY:
                    # We cannot prove that the provider side remained unchanged
                    # while its baseline was unavailable. Merge through the
                    # authoritative full reconciliation instead of guessing.
                    self.reconcile(self.job)
                    remote = new_remote
                    deferred_local.clear()
                    deferred_remote.clear()
                    recovery_due = time.monotonic() + 10.0
                    continue
                local_paths = {change.path for change in local_changes}
                remote_paths = {change.path for change in remote_changes}
                if local_paths & remote_paths and self.job.mode is SyncMode.TWO_WAY:
                    self.reconcile(self.job)
                    deferred_local.clear()
                    deferred_remote.clear()
                    recovery_due = time.monotonic() + 10.0
                else:
                    permitted = [
                        change for change in local_changes + remote_changes
                        if not (change.side == "local" and self.job.mode is SyncMode.DOWNLOAD_ONLY)
                        and not (change.side == "remote" and self.job.mode is SyncMode.UPLOAD_ONLY)
                    ]
                    applied = not permitted or self.apply(self.job, permitted)
                    if permitted and applied:
                        local_applied = [item for item in permitted if item.side == "local"]
                        remote_applied = [item for item in permitted if item.side == "remote"]
                        self._mirror(new_remote, local_applied, local)
                        self._mirror(local, remote_applied, new_remote)
                        recovery_due = time.monotonic() + 10.0
                    if permitted and not applied:
                        deferred_local.update({change.path: change for change in local_changes})
                        deferred_remote.update({
                            change.path: change for change in remote_changes
                        })
                    else:
                        deferred_local.clear()
                        deferred_remote.clear()
                remote = new_remote
                if local_changes or remote_changes:
                    backoff_index = 0
                else:
                    backoff_index = min(backoff_index + 1, len(self.remote_backoff) - 1)
                if self.remote_backoff:
                    remote_delay = self.remote_backoff[backoff_index]
                recovery_due = None if recovery_due is not None and time.monotonic() >= recovery_due else recovery_due
        finally:
            if events is not None:
                events.close()
