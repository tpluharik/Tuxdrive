"""Native Nautilus context menu and status integration for TuxDrive."""

from __future__ import annotations

import json
import os
from pathlib import Path

import gi

# Nautilus loads its own GI namespace before importing extensions. Do not pin
# a minor version here: Ubuntu 26.04 currently exposes 4.1, while earlier
# supported Nautilus 4 releases expose 4.0. Requiring either exact minor after
# the host has loaded the other prevents the complete extension from loading.
from gi.repository import Gio, GLib, GObject, Nautilus


APP_ID = "io.github.tuxdrive.TuxDrive"
APP_PATH = "/io/github/tuxdrive/TuxDrive"


def _config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tuxdrive" / "config.json"


def _jobs() -> list[dict]:
    try:
        value = json.loads(_config_path().read_text(encoding="utf-8"))
        if not value.get("settings", {}).get("nautilus_integration", True):
            return []
        return list(value.get("jobs", []))
    except (OSError, ValueError, TypeError):
        return []


def _state_path() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "tuxdrive" / "nautilus-state.json"


def _runtime_states() -> dict[str, dict]:
    try:
        value = json.loads(_state_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _local_path(file_info: Nautilus.FileInfo) -> Path | None:
    location = file_info.get_location()
    value = location.get_path() if location else None
    # Never resolve/stat a path from Nautilus. A disconnected FUSE child can
    # return ENOTCONN, and an InfoProvider must not turn that into a directory
    # listing failure. Lexical normalization is sufficient for configured roots.
    return Path(os.path.abspath(os.path.expanduser(value))) if value else None


def _containing_job(path: Path) -> dict | None:
    matches: list[tuple[int, dict]] = []
    for job in _jobs():
        try:
            root = Path(os.path.abspath(os.path.expanduser(job["local_path"])))
            path.relative_to(root)
            matches.append((len(root.parts), job))
        except (KeyError, OSError, TypeError, ValueError):
            continue
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


class TuxDriveExtension(GObject.GObject, Nautilus.MenuProvider, Nautilus.InfoProvider):
    """Expose only local, configured TuxDrive paths to Nautilus."""

    def __init__(self) -> None:
        super().__init__()
        self._known_files: dict[str, Nautilus.FileInfo] = {}
        self._monitors: list[Gio.FileMonitor] = []
        for directory in {_config_path().parent, _state_path().parent}:
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
                monitor.connect("changed", self._metadata_changed)
                self._monitors.append(monitor)
            except GLib.Error:
                continue

    def _metadata_changed(self, _monitor, changed, _other, _event) -> None:
        if changed.get_basename() not in {"config.json", "nautilus-state.json"}:
            return
        for file_info in list(self._known_files.values()):
            try:
                file_info.invalidate_extension_info()
            except GLib.Error:
                continue

    def _activate(self, action: str, path: Path | None = None) -> None:
        if action in {"open-online-path", "offline-path", "online-only-path"}:
            # GApplication forwards this request to the primary TuxDrive
            # process. This avoids org.gtk.Actions discovery differences in
            # Nautilus 4.1 while preserving one application instance.
            Gio.Subprocess.new(
                [
                    "tuxdrive",
                    {
                        "open-online-path": "--open-online",
                        "offline-path": "--offline-path",
                        "online-only-path": "--online-only-path",
                    }[action],
                    str(path or ""),
                ],
                Gio.SubprocessFlags.NONE,
            )
            return
        group = Gio.DBusActionGroup.get(Gio.bus_get_sync(Gio.BusType.SESSION), APP_ID, APP_PATH)
        parameter = GLib.Variant("s", str(path or ""))
        if action in group.list_actions():
            group.activate_action(action, parameter)
            return

        # Start the registered desktop application, then retry without blocking Nautilus.
        Gio.Subprocess.new(["tuxdrive", "--background"], Gio.SubprocessFlags.NONE)

        def retry(remaining: int = 20) -> bool:
            refreshed = Gio.DBusActionGroup.get(Gio.bus_get_sync(Gio.BusType.SESSION), APP_ID, APP_PATH)
            if action in refreshed.list_actions():
                refreshed.activate_action(action, parameter)
                return GLib.SOURCE_REMOVE
            if remaining <= 1:
                return GLib.SOURCE_REMOVE
            GLib.timeout_add(150, retry, remaining - 1)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(150, retry)

    def get_file_items(self, files: list[Nautilus.FileInfo]) -> list[Nautilus.MenuItem]:
        if not files:
            return []
        paths = [_local_path(item) for item in files]
        if any(path is None for path in paths):
            return []
        jobs = [_containing_job(path) for path in paths if path]
        if not any(jobs):
            return []

        submenu = Nautilus.Menu()
        show = Nautilus.MenuItem(
            name="TuxDrive::Show",
            label="Show in TuxDrive",
            tip="Open TuxDrive and show synchronization status",
            icon="tuxdrive",
        )
        show.connect("activate", lambda _item: self._activate("show-path", paths[0]))
        submenu.append_item(show)

        unique_jobs = {job.get("id") for job in jobs if job}
        if len(unique_jobs) == 1 and jobs[0].get("mode") != "virtual_drive":
            sync = Nautilus.MenuItem(
                name="TuxDrive::Sync",
                label="Synchronize this TuxDrive folder now",
                tip="Start the configured safety-checked synchronization job",
                icon="tuxdrive-sync",
            )
            sync.connect("activate", lambda _item: self._activate("sync-path", paths[0]))
            submenu.append_item(sync)

        logs = Nautilus.MenuItem(
            name="TuxDrive::Logs",
            label="Open TuxDrive activity logs",
            tip="Open diagnostic and synchronization logs",
            icon="text-x-generic-symbolic",
        )
        logs.connect("activate", lambda _item: self._activate("open-logs", paths[0]))
        submenu.append_item(logs)

        if len(unique_jobs) == 1:
            online = Nautilus.MenuItem(
                name="TuxDrive::Online",
                label="Open online/cloud folder",
                tip="Open the corresponding provider page without creating a public share link",
                icon="web-browser-symbolic",
            )
            online.connect("activate", lambda _item: self._activate("open-online-path", paths[0]))
            submenu.append_item(online)
            if jobs[0].get("mode") == "virtual_drive":
                offline = Nautilus.MenuItem(
                    name="TuxDrive::Offline",
                    label="Always keep available offline",
                    tip="Hydrate this item and retain it in TuxDrive's local VFS cache",
                    icon="emblem-downloads-symbolic",
                )
                offline.connect("activate", lambda _item: self._activate("offline-path", paths[0]))
                submenu.append_item(offline)
                online_only = Nautilus.MenuItem(
                    name="TuxDrive::OnlineOnly",
                    label="Free local space (online only)",
                    tip="Remove this item's persistent offline rule and matching cached content",
                    icon="edit-clear-symbolic",
                )
                online_only.connect("activate", lambda _item: self._activate("online-only-path", paths[0]))
                submenu.append_item(online_only)

        root = Nautilus.MenuItem(
            name="TuxDrive::Root",
            label="TuxDrive",
            tip="TuxDrive synchronization actions",
            icon="tuxdrive",
        )
        root.set_submenu(submenu)
        return [root]

    def get_background_items(self, current_folder: Nautilus.FileInfo) -> list[Nautilus.MenuItem]:
        return self.get_file_items([current_folder])

    def _apply_file_info(self, file_info: Nautilus.FileInfo) -> None:
        path = _local_path(file_info)
        job = _containing_job(path) if path else None
        if not job:
            return
        self._known_files[file_info.get_uri()] = file_info
        # Retain enough live objects for normal directories without allowing a
        # long Nautilus session to grow without bound.
        while len(self._known_files) > 2048:
            self._known_files.pop(next(iter(self._known_files)))
        mode = job.get("mode")
        runtime = _runtime_states().get(str(job.get("id", "")), {})
        state = str(runtime.get("state") or (
            "error" if job.get("last_error") else
            "paused" if not job.get("enabled", True) else
            "streaming" if mode == "virtual_drive" else
            "synced" if job.get("initialized") else "pending"
        ))
        status = str(runtime.get("detail") or {
            "syncing": "TuxDrive is synchronizing",
            "synced": "Synchronized by TuxDrive",
            "streaming": "TuxDrive files on demand",
            "paused": "TuxDrive synchronization paused",
            "error": "TuxDrive needs attention",
            "pending": "TuxDrive synchronization pending",
        }.get(state, "Managed by TuxDrive"))
        file_info.add_string_attribute("tuxdrive_status", status)
        emblem = f"tuxdrive-{state}" if state in {"syncing", "synced", "streaming", "paused", "error", "pending"} else "tuxdrive-pending"
        file_info.add_emblem(emblem)

    def update_file_info_full(self, _provider, _handle, _closure, file_info: Nautilus.FileInfo):
        """Nautilus 4 InfoProvider vfunc; synchronous metadata completion."""
        self._apply_file_info(file_info)
        return Nautilus.OperationResult.COMPLETE

    def update_file_info(self, file_info: Nautilus.FileInfo):
        """Compatibility entry point for older python-nautilus bindings."""
        self._apply_file_info(file_info)
        return Nautilus.OperationResult.COMPLETE

    def cancel_update(self, _provider, _handle) -> None:
        return None
