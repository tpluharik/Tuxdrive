"""Native Nautilus context menu and status integration for TuxDrive."""

from __future__ import annotations

import json
import os
from pathlib import Path

import gi

gi.require_version("Nautilus", "4.0")
from gi.repository import Gio, GLib, GObject, Nautilus


APP_ID = "io.github.tuxdrive.TuxDrive"
APP_PATH = "/io/github/tuxdrive/TuxDrive"


def _config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tuxdrive" / "config.json"


def _jobs() -> list[dict]:
    try:
        value = json.loads(_config_path().read_text(encoding="utf-8"))
        return [item for item in value.get("jobs", []) if item.get("enabled", True)]
    except (OSError, ValueError, TypeError):
        return []


def _local_path(file_info: Nautilus.FileInfo) -> Path | None:
    location = file_info.get_location()
    value = location.get_path() if location else None
    return Path(value).resolve(strict=False) if value else None


def _containing_job(path: Path) -> dict | None:
    matches: list[tuple[int, dict]] = []
    for job in _jobs():
        try:
            root = Path(job["local_path"]).expanduser().resolve(strict=False)
            path.relative_to(root)
            matches.append((len(root.parts), job))
        except (KeyError, TypeError, ValueError):
            continue
    return max(matches, default=(0, None), key=lambda item: item[0])[1]


class TuxDriveExtension(GObject.GObject, Nautilus.MenuProvider, Nautilus.InfoProvider):
    """Expose only local, configured TuxDrive paths to Nautilus."""

    def _activate(self, action: str, path: Path | None = None) -> None:
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

    def update_file_info(self, file_info: Nautilus.FileInfo) -> None:
        path = _local_path(file_info)
        job = _containing_job(path) if path else None
        if not job:
            return
        mode = job.get("mode")
        status = "TuxDrive files on demand" if mode == "virtual_drive" else "Synchronized by TuxDrive"
        file_info.add_string_attribute("tuxdrive_status", status)
        file_info.add_emblem("emblem-important" if job.get("last_error") else "emblem-synchronized")
