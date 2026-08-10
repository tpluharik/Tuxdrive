from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import threading
import tempfile
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .diagnostics import (
    application_log_path,
    configure_logging,
    crash_log_path,
    install_crash_handlers,
    log_boot_failure,
    log_directory,
)

LOGGER = configure_logging(__version__)
install_crash_handlers(LOGGER)

try:
    import gi

    # Pin GDK before importing it. Ubuntu 26.04 ships both GDK 3 and 4; without
    # this explicit requirement PyGObject may load GDK 4 before GTK 3.
    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, Gio, GLib
except (ImportError, ValueError) as exc:  # pragma: no cover - depends on host desktop
    message = (
        "TuxDrive could not load its desktop runtime. Reinstall with:\n\n"
        f"sudo apt install ./tuxdrive_{__version__}_all.deb\n\n"
        f"Technical detail: {exc}\nCrash log: {crash_log_path()}"
    )
    log_boot_failure(message)
    print(message, file=sys.stderr)
    if shutil.which("zenity"):
        subprocess.run(["zenity", "--error", "--title=TuxDrive startup failure", f"--text={message}"], check=False)
    raise SystemExit(2) from exc

from .audit import AuditTimeline
from .capabilities import CAPABILITIES, capabilities_for
from .config import ConfigStore, cache_home
from .engine import JobResult, SyncEngine
from .models import (
    Account, AppConfig, AuthorizedPeer, ConflictPolicy, OneTimeDrop, PeerRole, PeerShare, PeerTransportPolicy, Provider, SyncJob, SyncMode,
    paths_overlap, safe_streaming_overlap,
)
from .peer import DiscoveredPeer, PeerError, PeerInvitation, PeerManager, key_fingerprint, normalize_public_key, validate_host, validate_port
from .recovery import AuditIssue, IntegrityAuditor, RecoveryEntry, SafetyError
from .rclone import ConfigQuestion, ConfigResult, DriveLocation, RcloneClient, RcloneError
from .updater import UpdateManager, UpdateRelease
from .policies import TransferPolicy
from .migration import MigrationError, ProfileManager
from .platform_support import format_report, inspect_host

try:  # Ubuntu's AppIndicator extension provides Windows-like tray controls.
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3
except (ImportError, ValueError):  # pragma: no cover - optional desktop component
    AyatanaAppIndicator3 = None


APP_ID = "io.github.tuxdrive.TuxDrive"


def _desktop_open_command(target: str) -> list[str]:
    return ["open", target] if platform.system() == "Darwin" else ["xdg-open", target]


def _run_thread(function: Callable, callback: Callable, *args) -> None:
    def worker() -> None:
        try:
            result = function(*args)
            GLib.idle_add(callback, result, None)
        except Exception as exc:  # UI boundary: display backend errors to the user.
            GLib.idle_add(callback, None, exc)

    threading.Thread(target=worker, daemon=True).start()


class OAuthWizard(Gtk.Dialog):
    def __init__(
        self,
        parent: Gtk.Window,
        client: RcloneClient,
        provider: Provider,
        complete_callback: Callable[[Account], None],
        existing: Account | None = None,
    ) -> None:
        super().__init__(title=f"Connect {provider.label}", transient_for=parent, modal=True)
        self.set_icon_name(provider.icon_name)
        self.set_default_size(580, 460)
        self.client = client
        self.provider = provider
        self.complete_callback = complete_callback
        self.existing = existing
        self.question: ConfigQuestion | None = None
        self.remote = ""
        self.session_id = uuid.uuid4().hex
        self._closed = False
        self._initial_credentials: dict[str, str] = {}

        content = self.get_content_area()
        content.set_border_width(24)
        content.set_spacing(14)
        title = Gtk.Label()
        title.set_markup(f"<span size='x-large' weight='bold'>Connect {provider.label}</span>")
        title.set_xalign(0)
        content.pack_start(title, False, False, 0)
        description = Gtk.Label(label=(
            "Authorization opens in your default web browser. TuxDrive never sees your password."
            if provider.browser_oauth else
            "Follow the connection questions below. Use an app password where your provider supports one; credentials remain in rclone's private configuration."
        ))
        description.set_xalign(0)
        description.set_line_wrap(True)
        content.pack_start(description, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.name_entry = Gtk.Entry()
        self.name_entry.set_text(
            existing.remote if existing else
            provider.key_prefix + "-" + datetime.now().strftime("%H%M")
        )
        self.name_entry.set_sensitive(existing is None)
        self.display_entry = Gtk.Entry()
        self.display_entry.set_text(existing.display_name if existing else provider.label)
        self.client_id = Gtk.Entry()
        self.client_secret = Gtk.Entry()
        self.client_secret.set_visibility(False)
        grid.attach(Gtk.Label(label="Account key", xalign=0), 0, 0, 1, 1)
        grid.attach(self.name_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Display name", xalign=0), 0, 1, 1, 1)
        grid.attach(self.display_entry, 1, 1, 1, 1)
        if provider.browser_oauth:
            grid.attach(Gtk.Label(label="OAuth client ID (optional)", xalign=0), 0, 2, 1, 1)
            grid.attach(self.client_id, 1, 2, 1, 1)
            grid.attach(Gtk.Label(label="OAuth client secret (optional)", xalign=0), 0, 3, 1, 1)
            grid.attach(self.client_secret, 1, 3, 1, 1)
        self.credential_entries: dict[str, Gtk.Entry] = {}
        for offset, (key, label, secret, _required) in enumerate(provider.credential_fields, start=2):
            entry = Gtk.Entry()
            entry.set_visibility(not secret)
            if secret:
                entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
            grid.attach(Gtk.Label(label=label, xalign=0), 0, offset, 1, 1)
            grid.attach(entry, 1, offset, 1, 1)
            self.credential_entries[key] = entry
        content.pack_start(grid, False, False, 0)

        self.question_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.help_label = Gtk.Label(xalign=0)
        self.help_label.set_line_wrap(True)
        self.help_label.set_selectable(True)
        self.question_box.pack_start(self.help_label, False, False, 0)
        self.answer_widget: Gtk.Widget | None = None
        content.pack_start(self.question_box, True, True, 0)

        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(label="Ready", xalign=0)
        status_row = Gtk.Box(spacing=10)
        status_row.pack_start(self.spinner, False, False, 0)
        status_row.pack_start(self.status, True, True, 0)
        content.pack_start(status_row, False, False, 0)

        self.cancel_button = self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.next_button = self.add_button(
            "Open browser and connect" if provider.browser_oauth else "Configure connection",
            Gtk.ResponseType.OK,
        )
        self.connect("response", self._on_response)
        self.connect("delete-event", self._on_delete)
        self.show_all()
        self.question_box.hide()

    def _on_response(self, _dialog: Gtk.Dialog, response: int) -> None:
        if response != Gtk.ResponseType.OK:
            self._cancel_authorization()
            self.destroy()
            return
        if self.question is None:
            remote = self.name_entry.get_text().strip()
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", remote):
                self._set_error("Account key may contain only letters, numbers, dot, dash, and underscore.")
                return
            self.remote = remote
            credentials = {
                key: entry.get_text().strip()
                for key, entry in self.credential_entries.items()
            }
            self._initial_credentials = credentials
            missing = [
                label for key, label, _secret, required in self.provider.credential_fields
                if required and not credentials.get(key)
            ]
            if missing:
                self._set_error("Required: " + ", ".join(missing))
                return
            self._busy("Preparing secure authorization…")
            _run_thread(
                self.client.begin_oauth,
                self._step_ready,
                remote,
                self.provider,
                self.client_id.get_text().strip(),
                self.client_secret.get_text().strip(),
                self.session_id,
                credentials,
            )
        else:
            answer = self._answer()
            if self.question.required and not answer:
                self._set_error("This value is required.")
                return
            state = self.question.state
            self._busy("Waiting for authorization… Check your web browser.")
            _run_thread(
                self.client.continue_oauth,
                self._step_ready,
                self.remote,
                state,
                answer,
                self.session_id,
            )

    def _on_delete(self, *_args) -> bool:
        self._cancel_authorization()
        return False

    def _cancel_authorization(self) -> None:
        if not self._closed:
            self._closed = True
            self.client.cancel_oauth(self.session_id)

    def _step_ready(self, result: ConfigResult | None, error: Exception | None) -> bool:
        if self._closed:
            return False
        self._not_busy()
        if error:
            if (
                self.provider is Provider.PROTON_DRIVE
                and self.client.requires_proton_2fa(error)
            ):
                self._prompt_proton_2fa(str(error))
                return False
            self._set_error(str(error))
            return False
        if result is None:
            self._set_error("Authorization returned no result")
            return False
        if result.complete:
            self._busy("Verifying cloud access…")
            _run_thread(self.client.validate_remote, self._validation_ready, self.remote)
            return False
        self.question = result.question
        self._show_question(result.question)
        return False

    def _show_question(self, question: ConfigQuestion | None) -> None:
        if question is None:
            return
        self.name_entry.set_sensitive(False)
        self.display_entry.set_sensitive(False)
        self.client_id.set_sensitive(False)
        self.client_secret.set_sensitive(False)
        for entry in self.credential_entries.values():
            entry.set_sensitive(False)
        self.question_box.show()
        self.help_label.set_text((question.error + "\n\n" if question.error else "") + question.help)
        if self.answer_widget:
            self.question_box.remove(self.answer_widget)
        if question.examples:
            combo = Gtk.ComboBoxText()
            selected = 0
            for index, example in enumerate(question.examples):
                value = str(example.get("Value", ""))
                label = str(example.get("Help") or value)
                combo.append(value, label)
                if value == str(question.default):
                    selected = index
            combo.set_active(selected)
            self.answer_widget = combo
        else:
            entry = Gtk.Entry()
            entry.set_text("" if question.default is None else str(question.default))
            entry.set_visibility(not question.secret)
            self.answer_widget = entry
        self.question_box.pack_start(self.answer_widget, False, False, 0)
        self.answer_widget.show()
        self.next_button.set_label("Continue")
        self.status.set_text("Choose an option and continue")

    def _validation_ready(self, _result, error: Exception | None) -> bool:
        self._not_busy()
        if error:
            if (
                self.provider is Provider.PROTON_DRIVE
                and self.client.requires_proton_2fa(error)
            ):
                self._prompt_proton_2fa(str(error))
                return False
            self._set_error(f"Connection validation failed: {error}")
            return False
        account = Account(
            remote=self.remote,
            provider=self.provider,
            display_name=self.display_entry.get_text().strip() or self.provider.label,
        )
        self.complete_callback(account)
        self.destroy()
        return False

    def _prompt_proton_2fa(self, detail: str) -> None:
        dialog = Gtk.Dialog(title="Proton Drive two-factor authentication", transient_for=self, modal=True)
        dialog.set_icon_name(self.provider.icon_name)
        area = dialog.get_content_area()
        area.set_border_width(22)
        area.set_spacing(10)
        prompt = Gtk.Label(
            label=(
                "Proton requires a fresh two-factor authentication code. "
                "Open your authenticator app and enter the current six-digit code."
            ),
            xalign=0,
        )
        prompt.set_line_wrap(True)
        code = Gtk.Entry()
        code.set_placeholder_text("000000")
        code.set_max_length(12)
        code.set_input_purpose(Gtk.InputPurpose.DIGITS)
        code.set_activates_default(True)
        technical = Gtk.Expander(label="Technical detail")
        technical.add(Gtk.Label(label=detail, xalign=0, selectable=True, wrap=True))
        area.pack_start(prompt, False, False, 0)
        area.pack_start(code, False, False, 0)
        area.pack_start(technical, False, False, 0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        submit = dialog.add_button("Verify", Gtk.ResponseType.OK)
        submit.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        value = code.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            self._set_error("Proton Drive connection is waiting for two-factor authentication.")
            return
        if not re.fullmatch(r"[0-9]{6,12}", value):
            self._set_error("Enter the current numeric Proton two-factor authentication code.")
            return
        self._busy("Submitting Proton two-factor authentication…")
        credentials = dict(self._initial_credentials)
        credentials["2fa"] = value
        _run_thread(
            self.client.begin_oauth,
            self._step_ready,
            self.remote,
            self.provider,
            "",
            "",
            self.session_id,
            credentials,
        )

    def _answer(self) -> str:
        if isinstance(self.answer_widget, Gtk.ComboBoxText):
            return self.answer_widget.get_active_id() or ""
        if isinstance(self.answer_widget, Gtk.Entry):
            return self.answer_widget.get_text()
        return ""

    def _busy(self, message: str) -> None:
        self.spinner.start()
        self.status.set_text(message)
        self.next_button.set_sensitive(False)
        self.cancel_button.set_sensitive(True)

    def _not_busy(self) -> None:
        self.spinner.stop()
        self.next_button.set_sensitive(True)
        self.cancel_button.set_sensitive(True)

    def _set_error(self, message: str) -> None:
        self.status.set_markup(f"<span foreground='#c01c28'>{GLib.markup_escape_text(message)}</span>")


class CloudFolderTree(Gtk.Box):
    """Lazy-loading, multi-select cloud directory tree."""

    def __init__(self, client: RcloneClient, remote: str, selected: list[str] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.client = client
        self.remote = remote
        self.pending = {path.strip("/") for path in (selected or [])}
        self.store = Gtk.TreeStore(bool, str, str, bool)
        self.view = Gtk.TreeView(model=self.store)
        self.view.set_headers_visible(False)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self._toggle)
        self.view.append_column(Gtk.TreeViewColumn("Sync", toggle, active=0))
        folder = Gtk.CellRendererPixbuf(icon_name="folder-symbolic")
        label = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Cloud folder")
        column.pack_start(folder, False)
        column.pack_start(label, True)
        column.add_attribute(label, "text", 1)
        self.view.append_column(column)
        self.view.connect("row-expanded", self._expanded)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(250)
        scroll.add(self.view)
        self.pack_start(scroll, True, True, 0)
        self.status = Gtk.Label(label="Expand folders to browse the cloud drive.", xalign=0)
        self.status.set_line_wrap(True)
        self.pack_start(self.status, False, False, 0)
        self.reset(remote, selected)

    def reset(self, remote: str, selected: list[str] | None = None) -> None:
        self.remote = remote
        self.pending = {path.strip("/") for path in (selected or [])}
        self.store.clear()
        root_selected = "" in self.pending or not self.pending
        root = self.store.append(None, [root_selected, "Entire cloud drive", "", False])
        self.store.append(root, [False, "Loading…", "", True])
        self.view.expand_row(self.store.get_path(root), False)
        self._load(root)

    def selections(self) -> list[str]:
        values: list[str] = []

        def collect(model, _path, tree_iter, _data) -> bool:
            if model.get_value(tree_iter, 0) and model.get_value(tree_iter, 1) != "Loading…":
                values.append(model.get_value(tree_iter, 2))
            return False

        self.store.foreach(collect, None)
        return values

    def _toggle(self, _renderer, path: str) -> None:
        tree_iter = self.store.get_iter(path)
        selected = not self.store.get_value(tree_iter, 0)
        self.store.set_value(tree_iter, 0, selected)
        if selected:
            parent = self.store.iter_parent(tree_iter)
            while parent:
                self.store.set_value(parent, 0, False)
                parent = self.store.iter_parent(parent)
            self._clear_descendants(tree_iter)
        self.status.set_text(
            f"{len(self.selections())} cloud location(s) selected"
            if self.selections()
            else "Select at least one cloud folder or the entire drive."
        )

    def _clear_descendants(self, tree_iter) -> None:
        child = self.store.iter_children(tree_iter)
        while child:
            self.store.set_value(child, 0, False)
            self._clear_descendants(child)
            child = self.store.iter_next(child)

    def _expanded(self, _view, tree_iter, _path) -> None:
        self._load(tree_iter)

    def _load(self, tree_iter) -> None:
        if self.store.get_value(tree_iter, 3):
            return
        self.store.set_value(tree_iter, 3, True)
        cloud_path = self.store.get_value(tree_iter, 2)
        self.status.set_text(f"Loading {cloud_path or 'cloud drive'}…")
        _run_thread(
            self.client.list_directories,
            lambda folders, error, remote=self.remote, path=cloud_path: self._loaded(
                remote, path, folders, error
            ),
            self.remote,
            cloud_path,
        )

    def _loaded(
        self,
        remote: str,
        cloud_path: str,
        folders: list[str] | None,
        error: Exception | None,
    ) -> bool:
        if remote != self.remote:
            return False
        target = self._find_path(self.store.get_iter_first(), cloud_path)
        if target is None:
            return False
        child = self.store.iter_children(target)
        while child:
            self.store.remove(child)
            child = self.store.iter_children(target)
        if error:
            self.store.set_value(target, 3, False)
            detail = str(error)
            if "username and password are required" in detail.lower():
                detail += (
                    "\nOpen the Proton Drive account menu and choose "
                    "Reconnect / refresh credentials."
                )
            self.status.set_markup(
                f"<span foreground='#c01c28'>{GLib.markup_escape_text(detail)}</span>"
            )
            return False
        parent_path = self.store.get_value(target, 2)
        for name in folders or []:
            full_path = f"{parent_path}/{name}".strip("/")
            row = self.store.append(target, [full_path in self.pending, name, full_path, False])
            self.store.append(row, [False, "Loading…", full_path, True])
        self.status.set_text(f"{len(self.selections())} cloud location(s) selected")
        self._expand_pending(target)
        return False

    def _find_path(self, tree_iter, cloud_path: str):
        while tree_iter:
            if (
                self.store.get_value(tree_iter, 2) == cloud_path
                and self.store.get_value(tree_iter, 1) != "Loading…"
            ):
                return tree_iter
            nested = self._find_path(self.store.iter_children(tree_iter), cloud_path)
            if nested is not None:
                return nested
            tree_iter = self.store.iter_next(tree_iter)
        return None

    def _expand_pending(self, parent) -> None:
        parent_path = self.store.get_value(parent, 2)
        for wanted in self.pending:
            if not wanted or not wanted.startswith(f"{parent_path}/" if parent_path else ""):
                continue
            child = self.store.iter_children(parent)
            while child:
                child_path = self.store.get_value(child, 2)
                if wanted == child_path:
                    self.store.set_value(child, 0, True)
                    break
                if wanted.startswith(child_path + "/"):
                    self.view.expand_row(self.store.get_path(child), False)
                    self._load(child)
                    break
                child = self.store.iter_next(child)


class ExceptionRulesEditor(Gtk.Box):
    def __init__(self, rules: list[str]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.rule_list = Gtk.ListBox()
        self.rule_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(110)
        scroll.add(self.rule_list)
        self.pack_start(scroll, True, True, 0)
        add_row = Gtk.Box(spacing=6)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Example: /folder/file.zip or *.tmp")
        self.entry.connect("activate", lambda _entry: self._add_clicked(None))
        add_button = Gtk.Button(label="Add exception")
        add_button.connect("clicked", self._add_clicked)
        add_row.pack_start(self.entry, True, True, 0)
        add_row.pack_start(add_button, False, False, 0)
        self.pack_start(add_row, False, False, 0)
        for rule in rules:
            self.add_rule(rule)

    def rules(self) -> list[str]:
        return [row.rule for row in self.rule_list.get_children()]

    def add_rule(self, rule: str) -> None:
        cleaned = rule.strip()
        if not cleaned or cleaned in self.rules():
            return
        row = Gtk.ListBoxRow()
        row.rule = cleaned
        box = Gtk.Box(spacing=8)
        box.set_border_width(4)
        label = Gtk.Label(label=cleaned, xalign=0)
        label.set_selectable(True)
        remove = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
        remove.set_tooltip_text("Remove this synchronization exception")
        remove.connect("clicked", lambda _button: self.rule_list.remove(row))
        box.pack_start(label, True, True, 0)
        box.pack_end(remove, False, False, 0)
        row.add(box)
        self.rule_list.add(row)
        row.show_all()

    def _add_clicked(self, _button) -> None:
        self.add_rule(self.entry.get_text())
        self.entry.set_text("")


class SyncJobDialog(Gtk.Dialog):
    def __init__(
        self,
        parent: Gtk.Window,
        client: RcloneClient,
        accounts: list[Account],
        existing: SyncJob | None = None,
    ) -> None:
        super().__init__(
            title="Edit synchronized folder" if existing else "Add synchronized folder",
            transient_for=parent,
            modal=True,
        )
        self.set_default_size(760, 760)
        self.client = client
        self.accounts = accounts
        self.existing = existing
        content = self.get_content_area()
        content.set_border_width(24)
        grid = Gtk.Grid(column_spacing=14, row_spacing=12)
        content.pack_start(grid, True, True, 0)
        self.name = Gtk.Entry()
        self.name.set_text(existing.name if existing else "Cloud files")
        self.account = Gtk.ComboBoxText()
        for item in accounts:
            self.account.append(item.remote, f"{item.display_name} · {item.provider.label}")
        self.account.set_active_id(existing.account_remote if existing else accounts[0].remote)
        self.local = Gtk.FileChooserButton(title="Choose local folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        default = Path.home() / ("TuxDrive" if len(accounts) > 1 else accounts[0].provider.label.replace(" ", ""))
        self.local.set_filename(existing.local_path if existing else str(default))
        self.location = Gtk.ComboBoxText()
        self.location.set_sensitive(False)
        self.location.append("loading", "Loading cloud locations…")
        self.location.set_active_id("loading")
        self.locations: dict[str, DriveLocation] = {}
        self.folder_tree = CloudFolderTree(
            client,
            self.account.get_active_id(),
            [existing.remote_path] if existing else [""],
        )
        self.account.connect("changed", self._account_changed)
        self.location.connect("changed", self._location_changed)
        self._load_locations()
        self.mode = Gtk.ComboBoxText()
        for mode in SyncMode:
            self.mode.append(mode.value, mode.label)
        self.mode.set_active_id((existing.mode if existing else SyncMode.TWO_WAY).value)
        self.capability_note = Gtk.Label(xalign=0)
        self.capability_note.set_line_wrap(True)
        self.capability_note.get_style_context().add_class("dim-label")
        self._refresh_capabilities(existing.mode if existing else SyncMode.TWO_WAY)
        self.interval = Gtk.SpinButton.new_with_range(1, 1440, 1)
        self.interval.set_value(existing.interval_minutes if existing else 5)
        self.realtime_sync = Gtk.CheckButton(
            label="Sync saved file changes immediately (incremental)"
        )
        self.realtime_sync.set_active(existing.realtime_sync if existing else True)
        self.realtime_sync.set_tooltip_text(
            "Watches local saves and polls provider changes; transfers only changed paths."
        )
        self.block_delta = Gtk.CheckButton(label="Use block-level delta planning for changed files")
        self.block_delta.set_active(existing.block_delta_transfer if existing else True)
        self.block_delta.set_tooltip_text("Direct peer jobs exchange content-addressed changed blocks; cloud backends use their native transfer capabilities.")
        self._refresh_capabilities(existing.mode if existing else SyncMode.TWO_WAY)
        self.conflict = Gtk.ComboBoxText()
        for policy, label in (
            (ConflictPolicy.KEEP_BOTH, "Keep both copies"),
            (ConflictPolicy.NEWER_WINS, "Newer copy wins"),
            (ConflictPolicy.LOCAL_WINS, "Local copy wins"),
            (ConflictPolicy.CLOUD_WINS, "Cloud copy wins"),
        ):
            self.conflict.append(policy.value, label)
        self.conflict.set_active_id(
            (existing.conflict_policy if existing else ConflictPolicy.KEEP_BOTH).value
        )
        self.max_delete = Gtk.SpinButton.new_with_range(0, 100000, 10)
        self.max_delete.set_value(existing.max_delete if existing else 100)
        self.version_history = Gtk.CheckButton(label="Keep replaced and deleted files in local version history")
        self.version_history.set_active(existing.version_history if existing else True)
        self.retention = Gtk.SpinButton.new_with_range(1, 3650, 1)
        self.retention.set_value(existing.version_retention_days if existing else 30)
        self.ransomware = Gtk.CheckButton(label="Pause suspicious deletion, encryption, or mass-change bursts")
        self.ransomware.set_active(existing.ransomware_protection if existing else True)
        self.mass_limit = Gtk.SpinButton.new_with_range(10, 1000000, 10)
        self.mass_limit.set_value(existing.mass_change_limit if existing else 200)
        self.mass_percent = Gtk.SpinButton.new_with_range(1, 100, 1)
        self.mass_percent.set_value(existing.mass_change_percent if existing else 25)
        self.bandwidth = Gtk.Entry()
        self.bandwidth.set_placeholder_text("Optional, e.g. 10M")
        self.bandwidth.set_text(existing.bandwidth_limit if existing else "")
        self.acknowledge_abuse = Gtk.CheckButton(
            label="Allow downloading files Google flags as malware or spam (unsafe)"
        )
        self.acknowledge_abuse.set_active(
            existing.acknowledge_google_abuse if existing else False
        )
        self.acknowledge_abuse.set_tooltip_text(
            "Only enable this if you trust the flagged files. They may contain malware."
        )
        self.excludes = ExceptionRulesEditor(
            existing.exclude_patterns
            if existing
            else [".Trash-*/**", "*.part", "~$*"]
        )
        rows = [
            ("Name", self.name),
            ("Cloud account", self.account),
            ("Drive / cloud location", self.location),
            ("Local folder / mount point", self.local),
            ("Cloud folders to synchronize", self.folder_tree),
            ("Mode", self.mode),
            ("Provider capabilities", self.capability_note),
            ("Sync interval (minutes)", self.interval),
            ("Real-time callbacks", self.realtime_sync),
            ("Block-level delta transfer", self.block_delta),
            ("Conflict handling", self.conflict),
            ("Maximum deletions per run", self.max_delete),
            ("Local version history", self.version_history),
            ("Version retention (days)", self.retention),
            ("Ransomware protection", self.ransomware),
            ("Mass-change path limit", self.mass_limit),
            ("Mass-change percentage", self.mass_percent),
            ("Bandwidth limit", self.bandwidth),
            ("Google security warning", self.acknowledge_abuse),
            ("Synchronization exceptions", self.excludes),
        ]
        for row, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Save" if existing else "Add folder", Gtk.ResponseType.OK)
        self.show_all()

    def job(self) -> SyncJob:
        return self.jobs()[0]

    def jobs(self) -> list[SyncJob]:
        filename = self.local.get_filename() or str(Path.home() / "TuxDrive")
        excluded = self.excludes.rules()
        selections = self.folder_tree.selections()
        values: list[SyncJob] = []
        base_name = self.name.get_text().strip() or "Cloud files"
        for remote_path in selections:
            leaf = Path(remote_path).name if remote_path else "Cloud files"
            multi = len(selections) > 1
            selected_account = next(item for item in self.accounts if item.remote == self.account.get_active_id())
            value = SyncJob(
                name=f"{base_name} · {leaf}" if multi else base_name,
                account_remote=self.account.get_active_id(),
                remote_scope=self._selected_scope(),
                cloud_location_name=self._selected_location_name(),
                local_path=str(Path(filename) / leaf) if multi else filename,
                remote_path=remote_path,
                mode=SyncMode(self.mode.get_active_id()),
                interval_minutes=self.interval.get_value_as_int(),
                realtime_sync=self.realtime_sync.get_active(),
                block_delta_transfer=self.block_delta.get_active(),
                peer_delta=selected_account.provider is Provider.PEER,
                conflict_policy=ConflictPolicy(self.conflict.get_active_id()),
                max_delete=self.max_delete.get_value_as_int(),
                version_history=self.version_history.get_active(),
                version_retention_days=self.retention.get_value_as_int(),
                ransomware_protection=self.ransomware.get_active(),
                mass_change_limit=self.mass_limit.get_value_as_int(),
                mass_change_percent=self.mass_percent.get_value_as_int(),
                bandwidth_limit=self.bandwidth.get_text().strip(),
                acknowledge_google_abuse=self.acknowledge_abuse.get_active(),
                exclude_patterns=excluded,
            )
            values.append(value)
        if self.existing and values:
            value = values[0]
            value.id = self.existing.id
            value.initialized = self.existing.initialized
            value.enabled = self.existing.enabled
            value.last_run = self.existing.last_run
            value.last_status = self.existing.last_status
            value.last_error = self.existing.last_error
            value.offline_paths = list(self.existing.offline_paths)
            value.peer_role = self.existing.peer_role
            value.one_time_drop_id = self.existing.one_time_drop_id
            return [value]
        return values

    def _account_changed(self, combo: Gtk.ComboBoxText) -> None:
        remote = combo.get_active_id()
        if remote:
            self._load_locations()
            if hasattr(self, "mode"):
                self._refresh_capabilities()

    def _refresh_capabilities(self, preferred: SyncMode | None = None) -> None:
        remote = self.account.get_active_id()
        account = next((item for item in self.accounts if item.remote == remote), None)
        if not account:
            return
        capabilities = capabilities_for(account.provider)
        selected = preferred or SyncMode(self.mode.get_active_id() or SyncMode.TWO_WAY.value)
        self.mode.remove_all()
        for mode in SyncMode:
            if capabilities.supports_mode(mode):
                self.mode.append(mode.value, mode.label)
        if not capabilities.supports_mode(selected):
            selected = SyncMode.TWO_WAY
        self.mode.set_active_id(selected.value)
        features = [
            "streaming" if capabilities.streaming else "no streaming",
            "change polling" if capabilities.polling else "scheduled scans",
            "hash verification" if capabilities.hashes else "size/time verification",
            "share links" if capabilities.share_links else "no share links",
            "versions" if capabilities.versions else "no provider versions",
        ]
        self.capability_note.set_text(f"{account.provider.label}: {', '.join(features)}. {capabilities.notes}".strip())
        if hasattr(self, "block_delta"):
            self.block_delta.set_sensitive(account.provider is Provider.PEER)

    def _load_locations(self) -> None:
        remote = self.account.get_active_id()
        if not remote:
            return
        account = next(item for item in self.accounts if item.remote == remote)
        self.location.remove_all()
        self.locations = {}
        if account.provider is not Provider.GOOGLE_DRIVE:
            value = DriveLocation("default", account.provider.label, remote)
            self.locations[value.key] = value
            self.location.append(value.key, value.name)
            self.location.set_active_id(value.key)
            self.location.set_sensitive(False)
            self.folder_tree.reset(remote, [self.existing.remote_path] if self.existing else [""])
            return
        self.location.append("loading", "Loading My Drive and Shared Drives…")
        self.location.set_active_id("loading")
        self.location.set_sensitive(False)
        self.folder_tree.status.set_text("Discovering Google Drive locations…")
        _run_thread(
            self.client.google_drive_locations,
            lambda locations, error, requested=remote: self._locations_loaded(
                requested, locations, error
            ),
            remote,
        )

    def _locations_loaded(
        self,
        requested_remote: str,
        locations: list[DriveLocation] | None,
        error: Exception | None,
    ) -> bool:
        remote = self.account.get_active_id()
        if not remote or remote != requested_remote:
            return False
        if error:
            fallback = DriveLocation("configured", "Configured Google Drive root", remote)
            locations = [fallback]
            self.folder_tree.status.set_markup(
                f"<span foreground='#c01c28'>{GLib.markup_escape_text(str(error))}</span>"
            )
        self.location.remove_all()
        self.locations = {item.key: item for item in locations or []}
        for item in locations or []:
            self.location.append(item.key, item.name)
        preferred = None
        if self.existing:
            if self.existing.remote_scope:
                preferred = next(
                    (
                        item.key
                        for item in locations or []
                        if item.scoped_remote == self.existing.remote_scope
                    ),
                    None,
                )
            else:
                preferred = "configured"
        selected = preferred or (locations[0].key if locations else None)
        if selected:
            self.location.set_active_id(selected)
            self.location.set_sensitive(len(locations or []) > 1)
            location = self.locations[selected]
            initial = [self.existing.remote_path] if self.existing else [""]
            self.folder_tree.reset(location.scoped_remote, initial)
        return False

    def _location_changed(self, combo: Gtk.ComboBoxText) -> None:
        key = combo.get_active_id()
        location = self.locations.get(key)
        if location:
            self.folder_tree.reset(location.scoped_remote, [""])

    def _selected_scope(self) -> str:
        location = self.locations.get(self.location.get_active_id())
        return location.scoped_remote if location else self.account.get_active_id()

    def _selected_location_name(self) -> str:
        location = self.locations.get(self.location.get_active_id())
        return location.name if location else "Cloud drive"


class RecoveryHistoryDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, controller: "TuxDriveApplication", job: SyncJob) -> None:
        super().__init__(title=f"Version history · {job.name}", transient_for=parent, modal=True)
        self.set_default_size(760, 480)
        self.controller, self.job = controller, job
        area = self.get_content_area()
        area.set_border_width(16)
        self.store = Gtk.ListStore(str, str, str, str, object)
        view = Gtk.TreeView(model=self.store)
        for index, title in enumerate(("File", "Saved", "Reason", "Size")):
            view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index))
        for entry in controller.engine.recovery.entries(job.id):
            self.store.append([entry.relative_path, entry.created_at[:19].replace("T", " "), entry.reason, str(entry.size), entry])
        self.view = view
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        area.pack_start(Gtk.Label(label="Select a saved version to restore it locally. The current file is archived first.", xalign=0), False, False, 8)
        area.pack_start(scroll, True, True, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.add_button("Restore selected", Gtk.ResponseType.OK)
        self.connect("response", self._response)
        self.show_all()

    def _response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response != Gtk.ResponseType.OK:
            dialog.destroy()
            return
        model, selected = self.view.get_selection().get_selected()
        if selected:
            entry = model[selected][4]
            try:
                self.controller.engine.recovery.restore(self.job, entry)
                self.job.last_status = f"Restored {entry.relative_path}; synchronization queued"
                self.controller.save()
                self.controller.run_job(self.job)
            except SafetyError as exc:
                self.get_transient_for().message(str(exc), Gtk.MessageType.ERROR)
        dialog.destroy()


class IntegrityDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, controller: "TuxDriveApplication", job: SyncJob, conflicts_only: bool = False) -> None:
        super().__init__(title=("Conflict review center" if conflicts_only else "Integrity audit and repair"), transient_for=parent, modal=True)
        self.set_default_size(800, 520)
        self.controller, self.job, self.conflicts_only = controller, job, conflicts_only
        area = self.get_content_area()
        area.set_border_width(16)
        self.status = Gtk.Label(label="Comparing local and remote content…", xalign=0)
        area.pack_start(self.status, False, False, 8)
        self.store = Gtk.ListStore(bool, str, str, object)
        view = Gtk.TreeView(model=self.store)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", lambda _cell, path: self.store.set_value(self.store.get_iter(path), 0, not self.store[path][0]))
        view.append_column(Gtk.TreeViewColumn("Repair", toggle, active=0))
        view.append_column(Gtk.TreeViewColumn("Path", Gtk.CellRendererText(), text=1))
        view.append_column(Gtk.TreeViewColumn("Finding", Gtk.CellRendererText(), text=2))
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        area.pack_start(scroll, True, True, 0)
        self.local_button = self.add_button("Use local versions", 1)
        self.remote_button = self.add_button("Use cloud/peer versions", 2)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.local_button.set_sensitive(False)
        self.remote_button.set_sensitive(False)
        self.connect("response", self._response)
        self.show_all()
        account = next((item for item in controller.config.accounts if item.remote == job.account_remote), None)
        auditor = IntegrityAuditor(controller.engine.rclone_path, controller.engine.recovery)
        _run_thread(auditor.audit, self._loaded, job, bool(account and account.provider is Provider.VAULT))

    def _loaded(self, issues: list[AuditIssue] | None, error: Exception | None) -> bool:
        if error:
            self.status.set_text(f"Audit failed safely: {error}")
            return False
        visible = [item for item in (issues or []) if not self.conflicts_only or item.symbol == "*"]
        for issue in visible:
            self.store.append([True, issue.path, issue.description, issue])
        self.status.set_text(f"{len(visible)} conflict(s) found." if self.conflicts_only else f"Audit complete: {len(visible)} difference(s) require review.")
        self.local_button.set_sensitive(bool(visible))
        self.remote_button.set_sensitive(bool(visible))
        return False

    def _response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response not in (1, 2):
            dialog.destroy()
            return
        issues = [row[3] for row in self.store if row[0]]
        if not issues:
            return
        winner = "local" if response == 1 else "remote"
        confirm = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.OK_CANCEL, text=f"Repair {len(issues)} item(s) using {winner} as the authoritative side?")
        accepted = confirm.run() == Gtk.ResponseType.OK
        confirm.destroy()
        if not accepted:
            return
        auditor = IntegrityAuditor(self.controller.engine.rclone_path, self.controller.engine.recovery)
        _run_thread(auditor.repair, self._repaired, self.job, issues, winner)

    def _repaired(self, count: int | None, error: Exception | None) -> bool:
        if error:
            self.status.set_text(f"Repair stopped safely: {error}")
        else:
            self.status.set_text(f"Repair complete: {count} item(s). Run Verify again to confirm integrity.")
            self.local_button.set_sensitive(False)
            self.remote_button.set_sensitive(False)
        return False


class VaultDialog(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, controller: "TuxDriveApplication") -> None:
        super().__init__(title="Create encrypted cloud vault", transient_for=parent, modal=True)
        self.controller = controller
        area = self.get_content_area()
        area.set_border_width(20)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        area.pack_start(grid, True, True, 0)
        self.remote, self.name, self.folder = Gtk.Entry(), Gtk.Entry(), Gtk.Entry()
        self.remote.set_text(f"vault-{uuid.uuid4().hex[:6]}")
        self.name.set_text("Encrypted vault")
        self.folder.set_text("TuxDriveEncrypted")
        self.base = Gtk.ComboBoxText()
        bases = [item for item in controller.config.accounts if item.provider not in {Provider.PEER, Provider.VAULT}]
        for item in bases:
            self.base.append(item.remote, f"{item.display_name} · {item.provider.label}")
        if bases:
            self.base.set_active(0)
        self.password, self.confirm, self.salt = Gtk.Entry(), Gtk.Entry(), Gtk.Entry()
        for entry in (self.password, self.confirm, self.salt):
            entry.set_visibility(False)
        self.mode = Gtk.ComboBoxText()
        for value, label in (("standard", "Encrypt file and folder names"), ("obfuscate", "Obfuscate names"), ("off", "Keep names visible")):
            self.mode.append(value, label)
        self.mode.set_active_id("standard")
        rows = (("Vault key", self.remote), ("Display name", self.name), ("Storage account", self.base), ("Dedicated encrypted folder", self.folder), ("Vault password", self.password), ("Confirm password", self.confirm), ("Optional filename salt", self.salt), ("Filename protection", self.mode))
        for row, (label, widget) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        warning = Gtk.Label(label="Keep the password and optional salt in a password manager. TuxDrive cannot recover them. Never point a vault at a folder containing unencrypted files.", xalign=0)
        warning.set_line_wrap(True)
        grid.attach(warning, 0, len(rows), 2, 1)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Create vault", Gtk.ResponseType.OK)
        self.show_all()

    def create(self) -> Account:
        if self.password.get_text() != self.confirm.get_text():
            raise RcloneError("The vault passwords do not match")
        base = self.base.get_active_id()
        folder = self.folder.get_text().strip().strip("/")
        if not base or not folder or ".." in Path(folder).parts:
            raise RcloneError("Choose a storage account and a safe dedicated folder")
        remote = self.remote.get_text().strip()
        spec = f"{base}:{folder}"
        self.controller.rclone.create_crypt_remote(remote, spec, self.password.get_text(), self.salt.get_text(), self.mode.get_active_id())
        return Account(remote=remote, provider=Provider.VAULT, display_name=self.name.get_text().strip() or "Encrypted vault", vault_base_remote=base, vault_base_path=folder)


class PeerSharingDialog(Gtk.Dialog):
    """Manage direct encrypted folders and connections without an intermediary."""

    def __init__(self, parent: Gtk.Window, controller: "TuxDriveApplication") -> None:
        super().__init__(title="Peer-to-peer shared folders", transient_for=parent, modal=True)
        self.set_icon_name("tuxdrive")
        self.set_default_size(760, 680)
        self.controller = controller
        self.loaded_invitation: PeerInvitation | None = None
        area = self.get_content_area()
        area.set_border_width(20)
        area.set_spacing(12)
        explanation = Gtk.Label(
            label=(
                "TuxDrive connects computers over encrypted, host-key-pinned SFTP. "
                "Files are never stored by an intermediary. Use direct addressing, automatic "
                "router mapping, or the optional ciphertext-only reverse relay."
            ),
            xalign=0,
        )
        explanation.set_line_wrap(True)
        area.pack_start(explanation, False, False, 0)
        try:
            identity_key = controller.peers.identity_public_key()
        except Exception as exc:
            identity_key = f"Key generation failed: {exc}"
        identity = Gtk.Expander(label="This computer’s public identity key")
        identity_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        identity_value = Gtk.Entry()
        identity_value.set_text(identity_key)
        identity_value.set_editable(False)
        copy_identity = Gtk.Button(label="Copy public key")
        copy_identity.connect(
            "clicked",
            lambda _button: Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(identity_key, -1),
        )
        identity_box.pack_start(identity_value, False, False, 0)
        identity_box.pack_start(copy_identity, False, False, 0)
        identity.add(identity_box)
        area.pack_start(identity, False, False, 0)

        notebook = Gtk.Notebook()
        notebook.append_page(self._host_page(), Gtk.Label(label="Share a folder"))
        notebook.append_page(self._client_page(), Gtk.Label(label="Connect to a peer"))
        notebook.append_page(self._lan_page(), Gtk.Label(label="Find on LAN"))
        area.pack_start(notebook, True, True, 0)
        self.status = Gtk.Label(xalign=0)
        self.status.set_line_wrap(True)
        area.pack_start(self.status, False, False, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dialog, _response: dialog.destroy())
        self.show_all()
        self._reload_share_choices()
        self._reload_connection_choices()

    @staticmethod
    def _folder_button(title: str) -> Gtk.FileChooserButton:
        chooser = Gtk.FileChooserButton(title=title, action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.set_create_folders(True)
        return chooser

    @staticmethod
    def _row(grid: Gtk.Grid, row: int, label: str, widget: Gtk.Widget) -> None:
        grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
        grid.attach(widget, 1, row, 1, 1)

    def _host_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(12)
        self.share_choice = Gtk.ComboBoxText()
        self.share_choice.connect("changed", self._load_share)
        self.share_name = Gtk.Entry()
        self.share_folder = self._folder_button("Folder to share directly")
        self.share_host = Gtk.Entry()
        self.share_host.set_placeholder_text("Public/LAN IP or DNS name")
        self.share_port = Gtk.SpinButton.new_with_range(1024, 65535, 1)
        self.share_port.set_value(2022)
        self.peer_store = Gtk.ListStore(bool, str, str, str)
        peer_view = Gtk.TreeView(model=self.peer_store)
        enabled = Gtk.CellRendererToggle()
        enabled.connect("toggled", lambda _cell, path: self.peer_store.set_value(self.peer_store.get_iter(path), 0, not self.peer_store[path][0]))
        peer_view.append_column(Gtk.TreeViewColumn("Enabled", enabled, active=0))
        peer_view.append_column(Gtk.TreeViewColumn("Device", Gtk.CellRendererText(), text=1))
        peer_view.append_column(Gtk.TreeViewColumn("Public key", Gtk.CellRendererText(), text=2))
        peer_view.append_column(Gtk.TreeViewColumn("Role", Gtk.CellRendererText(), text=3))
        self.peer_view = peer_view
        peer_scroll = Gtk.ScrolledWindow()
        peer_scroll.set_min_content_height(115)
        peer_scroll.add(peer_view)
        self.peer_name = Gtk.Entry()
        self.peer_name.set_placeholder_text("Device name")
        self.share_peer_key = Gtk.Entry()
        self.share_peer_key.set_placeholder_text("Peer’s ssh-ed25519 public key")
        self.peer_role = Gtk.ComboBoxText()
        for role in PeerRole:
            self.peer_role.append(role.value, role.label)
        self.peer_role.set_active_id(PeerRole.READ_WRITE.value)
        peer_add = Gtk.Button(label="Authorize device")
        peer_add.connect("clicked", self._add_authorized_peer)
        peer_remove = Gtk.Button(label="Revoke selected")
        peer_remove.connect("clicked", self._remove_authorized_peer)
        peer_set_role = Gtk.Button(label="Set selected role")
        peer_set_role.connect("clicked", self._set_authorized_peer_role)
        peer_editor = Gtk.Box(spacing=6)
        peer_editor.pack_start(self.peer_name, False, False, 0)
        peer_editor.pack_start(self.share_peer_key, True, True, 0)
        peer_editor.pack_start(self.peer_role, False, False, 0)
        peer_editor.pack_start(peer_add, False, False, 0)
        peer_editor.pack_start(peer_set_role, False, False, 0)
        peer_editor.pack_start(peer_remove, False, False, 0)
        peer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        peer_box.pack_start(peer_scroll, True, True, 0)
        peer_box.pack_start(peer_editor, False, False, 0)
        self.share_discovery = Gtk.CheckButton(label="Advertise this share on the local network")
        self.share_discovery.set_active(True)
        self.share_lease_minutes = Gtk.SpinButton.new_with_range(1, 1440, 1)
        self.share_lease_minutes.set_value(10)
        self.share_nat = Gtk.CheckButton(label="Automatically request UPnP/NAT-PMP port mapping")
        self.share_nat.set_active(True)
        self.transport_policy = Gtk.ComboBoxText()
        self.transport_policy.append(PeerTransportPolicy.AUTO.value, "Automatic (direct, then configured alternatives)")
        self.transport_policy.append(PeerTransportPolicy.DIRECT_ONLY.value, "Direct only")
        self.transport_policy.append(PeerTransportPolicy.TOR_ONLY.value, "Tor only (fail closed)")
        self.transport_policy.set_active_id(PeerTransportPolicy.AUTO.value)
        self.onion_enabled = Gtk.CheckButton(label="Publish a Tor v3 Onion Service")
        self.onion_persistent = Gtk.CheckButton(label="Keep the Onion address across restarts")
        self.onion_persistent.set_active(True)
        self.onion_client_auth = Gtk.CheckButton(label="Require per-device Onion client authorization")
        self.no_relay = Gtk.CheckButton(label="Never use a relay")
        self.no_public_ip = Gtk.CheckButton(label="Do not discover or advertise a public IP")
        self.never_cloud = Gtk.CheckButton(label="Never use provider cloud for this workspace")
        self.never_cloud.set_active(True)
        self.tor_bridges = Gtk.Entry()
        self.tor_bridges.set_placeholder_text("Optional bridge line; kept out of invitations and logs")
        self.tor_transport_plugin = Gtk.Entry()
        self.tor_transport_plugin.set_placeholder_text("Optional, e.g. obfs4 exec /usr/bin/obfs4proxy")
        self.relay_host = Gtk.Entry()
        self.relay_host.set_placeholder_text("Optional SSH relay host (forwards ciphertext only)")
        self.relay_user = Gtk.Entry()
        self.relay_user.set_placeholder_text("Relay SSH user")
        self.relay_ssh_port = Gtk.SpinButton.new_with_range(1, 65535, 1)
        self.relay_ssh_port.set_value(22)
        self.relay_public_port = Gtk.SpinButton.new_with_range(0, 65535, 1)
        self.relay_public_port.set_value(0)
        self.drop_expiry = Gtk.SpinButton.new_with_range(1, 168, 1)
        self.drop_expiry.set_value(24)
        grid = Gtk.Grid(column_spacing=12, row_spacing=9)
        self._row(grid, 0, "Saved share", self.share_choice)
        self._row(grid, 1, "Display name", self.share_name)
        self._row(grid, 2, "Local folder", self.share_folder)
        self._row(grid, 3, "Address peers use", self.share_host)
        self._row(grid, 4, "TCP port", self.share_port)
        self._row(grid, 5, "Authorized peer devices", peer_box)
        self._row(grid, 6, "LAN discovery", self.share_discovery)
        self._row(grid, 7, "Edit lease duration (minutes)", self.share_lease_minutes)
        self._row(grid, 8, "NAT traversal", self.share_nat)
        self._row(grid, 9, "No-storage relay host", self.relay_host)
        self._row(grid, 10, "Relay SSH user", self.relay_user)
        self._row(grid, 11, "Relay SSH port", self.relay_ssh_port)
        self._row(grid, 12, "Relay public forwarding port", self.relay_public_port)
        self._row(grid, 13, "Transport policy", self.transport_policy)
        self._row(grid, 14, "Tor v3 service", self.onion_enabled)
        self._row(grid, 15, "Onion identity", self.onion_persistent)
        self._row(grid, 16, "Onion authorization", self.onion_client_auth)
        self._row(grid, 17, "Fail-closed restrictions", self.no_relay)
        self._row(grid, 18, "IP privacy", self.no_public_ip)
        self._row(grid, 19, "Cloud isolation", self.never_cloud)
        self._row(grid, 20, "Tor bridge profile", self.tor_bridges)
        self._row(grid, 21, "Pluggable transport", self.tor_transport_plugin)
        page.pack_start(grid, False, False, 0)
        note = Gtk.Label(
            label=(
                "Exchange identity keys through a trusted channel. If this address is behind a router, "
                "forward the selected TCP port to this computer and permit it in the firewall."
            ),
            xalign=0,
        )
        note.set_line_wrap(True)
        page.pack_start(note, False, False, 0)
        buttons = Gtk.Box(spacing=8)
        save = Gtk.Button(label="Save and start")
        save.connect("clicked", self._save_share)
        stop = Gtk.Button(label="Stop")
        stop.connect("clicked", self._stop_share)
        invitation = Gtk.Button(label="Copy invitation")
        invitation.connect("clicked", self._copy_invitation)
        qr = Gtk.Button(label="Show invitation QR")
        qr.connect("clicked", self._show_invitation_qr)
        file_drop = Gtk.Button(label="Create one-time file drop")
        file_drop.set_tooltip_text("Uses the device name/public key fields and creates an expiring upload-only inbox")
        file_drop.connect("clicked", self._create_file_drop)
        delete = Gtk.Button(label="Delete")
        delete.connect("clicked", self._delete_share)
        buttons.pack_start(Gtk.Label(label="Drop expires (hours):"), False, False, 0)
        buttons.pack_start(self.drop_expiry, False, False, 0)
        for button in (save, stop, invitation, qr, file_drop, delete):
            buttons.pack_start(button, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    def _client_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(12)
        self.connection_choice = Gtk.ComboBoxText()
        self.connection_choice.connect("changed", self._load_connection)
        self.connection_name = Gtk.Entry()
        self.connection_host = Gtk.Entry()
        self.connection_port = Gtk.SpinButton.new_with_range(1024, 65535, 1)
        self.connection_port.set_value(2022)
        self.connection_host_key = Gtk.Entry()
        self.connection_host_key.set_placeholder_text("Host key from the invitation")
        self.connection_folder = self._folder_button("Local synchronized folder")
        self.connection_lease = Gtk.SpinButton.new_with_range(1, 1440, 1)
        self.connection_lease.set_value(10)
        grid = Gtk.Grid(column_spacing=12, row_spacing=9)
        self._row(grid, 0, "Saved connection", self.connection_choice)
        self._row(grid, 1, "Display name", self.connection_name)
        self._row(grid, 2, "Peer IP / DNS", self.connection_host)
        self._row(grid, 3, "Peer TCP port", self.connection_port)
        self._row(grid, 4, "Peer host public key", self.connection_host_key)
        self._row(grid, 5, "My local folder", self.connection_folder)
        self._row(grid, 6, "Cooperative edit lease (minutes)", self.connection_lease)
        page.pack_start(grid, False, False, 0)
        invitation_label = Gtk.Label(label="Paste invitation from the sharing computer", xalign=0)
        page.pack_start(invitation_label, False, False, 0)
        self.invitation_text = Gtk.TextView()
        self.invitation_text.set_monospace(True)
        invitation_scroll = Gtk.ScrolledWindow()
        invitation_scroll.set_min_content_height(100)
        invitation_scroll.add(self.invitation_text)
        page.pack_start(invitation_scroll, True, True, 0)
        buttons = Gtk.Box(spacing=8)
        load = Gtk.Button(label="Load invitation")
        load.connect("clicked", self._load_invitation)
        scan = Gtk.Button(label="Import QR image")
        scan.connect("clicked", self._scan_qr)
        connect = Gtk.Button(label="Save and connect")
        connect.connect("clicked", self._save_connection)
        delete = Gtk.Button(label="Remove connection")
        delete.connect("clicked", self._delete_connection)
        for button in (load, scan, connect, delete):
            buttons.pack_start(button, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    def _lan_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page.set_border_width(12)
        label = Gtk.Label(label="Discovery is local-network only. Verify the displayed host-key fingerprint with the sharing user before connecting.", xalign=0)
        label.set_line_wrap(True)
        page.pack_start(label, False, False, 0)
        self.discovery_store = Gtk.ListStore(str, str, str, object)
        self.discovery_view = Gtk.TreeView(model=self.discovery_store)
        for index, title in enumerate(("Share", "Address", "Host-key fingerprint")):
            self.discovery_view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=index))
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.discovery_view)
        page.pack_start(scroll, True, True, 0)
        buttons = Gtk.Box(spacing=8)
        find = Gtk.Button(label="Scan local network")
        find.connect("clicked", self._discover_lan)
        use = Gtk.Button(label="Use selected peer")
        use.connect("clicked", self._use_discovered)
        buttons.pack_start(find, False, False, 0)
        buttons.pack_start(use, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        return page

    def _reload_share_choices(self, selected: str = "new") -> None:
        self.share_choice.remove_all()
        self.share_choice.append("new", "New shared folder")
        for share in self.controller.config.peer_shares:
            state = "running" if share.id in self.controller.peers.running_shares else "stopped"
            self.share_choice.append(share.id, f"{share.name} · {state}")
        self.share_choice.set_active_id(selected)

    def _selected_share(self) -> PeerShare | None:
        share_id = self.share_choice.get_active_id()
        return next((item for item in self.controller.config.peer_shares if item.id == share_id), None)

    def _load_share(self, _combo: Gtk.ComboBoxText) -> None:
        share = self._selected_share()
        self.share_name.set_text(share.name if share else "Peer shared folder")
        self.share_host.set_text(share.advertised_host if share else "")
        self.share_port.set_value(share.port if share else 2022)
        self.peer_store.clear()
        if share:
            peers = share.authorized_peers or ([AuthorizedPeer("Legacy peer", share.allowed_peer_key)] if share.allowed_peer_key else [])
            for peer in peers:
                self.peer_store.append([peer.enabled, peer.name, peer.public_key, peer.role.label])
        self.peer_name.set_text("")
        self.share_peer_key.set_text("")
        self.share_discovery.set_active(share.lan_discovery if share else True)
        self.share_lease_minutes.set_value(share.lease_minutes if share else 10)
        self.share_nat.set_active(share.nat_traversal if share else True)
        self.relay_host.set_text(share.relay_host if share else "")
        self.relay_user.set_text(share.relay_user if share else "")
        self.relay_ssh_port.set_value(share.relay_ssh_port if share else 22)
        self.relay_public_port.set_value(share.relay_public_port if share else 0)
        self.transport_policy.set_active_id(share.transport_policy.value if share else PeerTransportPolicy.AUTO.value)
        self.onion_enabled.set_active(share.onion_enabled if share else False)
        self.onion_persistent.set_active(share.onion_persistent if share else True)
        self.onion_client_auth.set_active(share.onion_client_auth if share else False)
        self.no_relay.set_active(share.no_relay if share else False)
        self.no_public_ip.set_active(share.no_public_ip_discovery if share else False)
        self.never_cloud.set_active(share.never_use_provider_cloud if share else True)
        self.tor_bridges.set_text(share.tor_bridge_lines[0] if share and share.tor_bridge_lines else "")
        self.tor_transport_plugin.set_text(share.tor_pluggable_transports[0] if share and share.tor_pluggable_transports else "")
        if share and Path(share.local_path).is_dir():
            self.share_folder.set_filename(str(Path(share.local_path).expanduser()))

    def _save_share(self, _button: Gtk.Button) -> None:
        try:
            folder = self.share_folder.get_filename()
            if not folder:
                raise PeerError("Select the local folder to share")
            share = self._selected_share()
            name = self.share_name.get_text().strip() or "Peer shared folder"
            policy = PeerTransportPolicy(self.transport_policy.get_active_id() or PeerTransportPolicy.AUTO.value)
            advertised_host = self.share_host.get_text().strip()
            if not self.no_public_ip.get_active() and policy is not PeerTransportPolicy.TOR_ONLY:
                advertised_host = validate_host(advertised_host)
            port = validate_port(self.share_port.get_value_as_int())
            roles = {role.label: role for role in PeerRole}
            previous_auth = {item.public_key: item.onion_client_public_key for item in (share.authorized_peers if share else [])}
            authorized_peers = [AuthorizedPeer(row[1], normalize_public_key(row[2]), row[0], role=roles.get(row[3], PeerRole.READ_WRITE), onion_client_public_key=previous_auth.get(row[2], "")) for row in self.peer_store]
            if not any(item.enabled for item in authorized_peers):
                raise PeerError("Authorize at least one enabled peer device")
            if share is None:
                share = PeerShare("", folder, "")
                self.controller.config.peer_shares.append(share)
            else:
                self.controller.peers.stop(share.id)
            share.name = name
            share.local_path = folder
            share.advertised_host = advertised_host
            share.port = port
            share.allowed_peer_key = ""
            share.authorized_peers = authorized_peers
            share.lan_discovery = self.share_discovery.get_active()
            share.lease_minutes = self.share_lease_minutes.get_value_as_int()
            share.nat_traversal = self.share_nat.get_active()
            share.relay_host = self.relay_host.get_text().strip()
            share.relay_user = self.relay_user.get_text().strip()
            share.relay_ssh_port = self.relay_ssh_port.get_value_as_int()
            share.relay_public_port = self.relay_public_port.get_value_as_int()
            share.transport_policy = policy
            share.onion_enabled = self.onion_enabled.get_active()
            share.onion_persistent = self.onion_persistent.get_active()
            share.onion_client_auth = self.onion_client_auth.get_active()
            share.no_relay = self.no_relay.get_active()
            share.no_public_ip_discovery = self.no_public_ip.get_active()
            share.never_use_provider_cloud = self.never_cloud.get_active()
            bridge = self.tor_bridges.get_text().strip()
            share.tor_bridge_lines = [bridge] if bridge else []
            plugin = self.tor_transport_plugin.get_text().strip()
            share.tor_pluggable_transports = [plugin] if plugin else []
            share.enabled = True
            self.controller.peers.start(share)
            share.last_status = f"Listening at {share.onion_address}" if share.onion_enabled else f"Listening on TCP {share.port}"
            self.controller.save()
            self._reload_share_choices(share.id)
            self._set_status("Direct encrypted share is running.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _add_authorized_peer(self, _button: Gtk.Button) -> None:
        try:
            name = self.peer_name.get_text().strip() or f"Peer {len(self.peer_store) + 1}"
            key = normalize_public_key(self.share_peer_key.get_text())
            if any(row[2] == key for row in self.peer_store):
                raise PeerError("That public key is already authorized")
            role = PeerRole(self.peer_role.get_active_id() or PeerRole.READ_WRITE.value)
            self.peer_store.append([True, name, key, role.label])
            self.peer_name.set_text("")
            self.share_peer_key.set_text("")
            self._set_status(f"{name} added. Save and start to apply authorization.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _selected_peer_role(self) -> PeerRole:
        model, selected = self.peer_view.get_selection().get_selected()
        if not selected:
            return PeerRole.READ_WRITE
        return next((role for role in PeerRole if role.label == model[selected][3]), PeerRole.READ_WRITE)

    def _create_file_drop(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            self._set_status("Save and start the shared folder first.", True)
            return
        try:
            name = self.peer_name.get_text().strip() or "One-time sender"
            key = normalize_public_key(self.share_peer_key.get_text())
            expiry = datetime.now(timezone.utc) + timedelta(hours=self.drop_expiry.get_value_as_int())
            drop = OneTimeDrop(name, key, f".tuxdrive-drops/{uuid.uuid4().hex}", expiry.isoformat())
            share.one_time_drops.append(drop)
            self.controller.peers.stop(share.id)
            self.controller.peers.start(share)
            invitation = self.controller.peers.one_time_invitation(share, drop)
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(invitation, -1)
            self.controller.audit.record("peer", "one-time drop created", "success", peer=name, path=drop.inbox_path, detail=f"expires {drop.expires_at}")
            self.controller.save()
            self._set_status("Expiring upload-only invitation copied. It is revoked after the first received file.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _remove_authorized_peer(self, _button: Gtk.Button) -> None:
        model, selected = self.peer_view.get_selection().get_selected()
        if selected:
            name = model[selected][1]
            model.remove(selected)
            self._set_status(f"{name} revoked. Save and start to apply immediately.", False)

    def _set_authorized_peer_role(self, _button: Gtk.Button) -> None:
        model, selected = self.peer_view.get_selection().get_selected()
        if not selected:
            self._set_status("Select an authorized device first.", True)
            return
        role = PeerRole(self.peer_role.get_active_id() or PeerRole.READ_WRITE.value)
        model.set_value(selected, 3, role.label)
        self._set_status(f"Role changed to {role.label}. Save and start, then issue a new invitation.", False)

    def _stop_share(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            return
        self.controller.peers.stop(share.id)
        share.enabled = False
        share.last_status = "Stopped"
        self.controller.save()
        self._reload_share_choices(share.id)
        self._set_status("Share stopped.", False)

    def _copy_invitation(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            self._set_status("Save the shared folder first.", True)
            return
        try:
            role = self._selected_peer_role()
            model, selected = self.peer_view.get_selection().get_selected()
            peer_name = model[selected][1] if selected else ""
            value = self.controller.peers.invitation(share, role, peer_name)
            self.controller.save()
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(value, -1)
            self._set_status(f"{role.label} invitation copied. Send it through a trusted channel.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _show_invitation_qr(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            self._set_status("Save the shared folder first.", True)
            return
        try:
            model, selected = self.peer_view.get_selection().get_selected()
            peer_name = model[selected][1] if selected else ""
            value = self.controller.peers.invitation(share, self._selected_peer_role(), peer_name)
            self.controller.save()
            encoder = shutil.which("qrencode")
            if not encoder:
                raise PeerError("QR support is missing; reinstall the complete TuxDrive package")
            with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
                result = subprocess.run([encoder, "-o", image_file.name, "-s", "7", "--", value], capture_output=True, text=True, timeout=20, check=False)
                if result.returncode:
                    raise PeerError((result.stderr or "Could not generate QR code").strip())
                dialog = Gtk.Dialog(title=f"Pair with {share.name}", transient_for=self, modal=True)
                dialog.get_content_area().set_border_width(18)
                dialog.get_content_area().pack_start(Gtk.Image.new_from_file(image_file.name), True, True, 0)
                fingerprint = key_fingerprint(self.controller.peers.host_public_key(share))
                detail = Gtk.Label(label=f"Verify this host-key fingerprint on both computers:\n{fingerprint}")
                detail.set_selectable(True)
                dialog.get_content_area().pack_start(detail, False, False, 8)
                dialog.add_button("Close", Gtk.ResponseType.CLOSE)
                dialog.show_all()
                dialog.run()
                dialog.destroy()
        except Exception as exc:
            self._set_status(str(exc), True)

    def _delete_share(self, _button: Gtk.Button) -> None:
        share = self._selected_share()
        if not share:
            return
        self.controller.peers.stop(share.id)
        self.controller.config.peer_shares.remove(share)
        self.controller.save()
        self._reload_share_choices()
        self._set_status("Share definition removed; files were not deleted.", False)

    def _peer_accounts(self) -> list[Account]:
        return [item for item in self.controller.config.accounts if item.provider is Provider.PEER]

    def _reload_connection_choices(self, selected: str = "new") -> None:
        self.connection_choice.remove_all()
        self.connection_choice.append("new", "New peer connection")
        for account in self._peer_accounts():
            self.connection_choice.append(account.remote, account.display_name)
        self.connection_choice.set_active_id(selected)

    def _selected_connection(self) -> Account | None:
        remote = self.connection_choice.get_active_id()
        return next((item for item in self._peer_accounts() if item.remote == remote), None)

    def _load_connection(self, _combo: Gtk.ComboBoxText) -> None:
        account = self._selected_connection()
        self.connection_name.set_text(account.display_name if account else "Peer folder")
        self.connection_host.set_text(account.peer_host if account else "")
        self.connection_port.set_value(account.peer_port if account else 2022)
        self.connection_host_key.set_text(account.peer_host_key if account else "")
        if account:
            job = next((item for item in self.controller.config.jobs if item.account_remote == account.remote), None)
            if job and job.local.is_dir():
                self.connection_folder.set_filename(str(job.local))
            if job:
                self.connection_lease.set_value(job.peer_lease_minutes)

    def _load_invitation(self, _button: Gtk.Button) -> None:
        buffer = self.invitation_text.get_buffer()
        value = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        try:
            invitation = PeerInvitation.decode(value)
            self._apply_invitation(invitation)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _scan_qr(self, _button: Gtk.Button) -> None:
        chooser = Gtk.FileChooserDialog(title="Select invitation QR image", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
        chooser.add_button("Open", Gtk.ResponseType.OK)
        if chooser.run() == Gtk.ResponseType.OK:
            try:
                decoder = shutil.which("zbarimg")
                if not decoder:
                    raise PeerError("QR scanning support is missing; reinstall the complete TuxDrive package")
                result = subprocess.run([decoder, "--quiet", "--raw", chooser.get_filename()], capture_output=True, text=True, timeout=20, check=False)
                if result.returncode or not result.stdout.strip():
                    raise PeerError("No valid TuxDrive invitation QR code was found")
                invitation = PeerInvitation.decode(result.stdout.strip())
                self._apply_invitation(invitation)
            except Exception as exc:
                self._set_status(str(exc), True)
        chooser.destroy()

    def _apply_invitation(self, invitation: PeerInvitation) -> None:
        invitation.assert_usable()
        self.loaded_invitation = invitation
        self.connection_name.set_text(invitation.name)
        self.connection_host.set_text(invitation.host)
        self.connection_port.set_value(invitation.port)
        self.connection_host_key.set_text(invitation.host_key)
        self.connection_lease.set_value(invitation.lease_minutes)
        self._set_status(f"{invitation.role.label} invitation loaded. Verify fingerprint {key_fingerprint(invitation.host_key)} before connecting.", False)

    def _discover_lan(self, _button: Gtk.Button) -> None:
        self.discovery_store.clear()
        self._set_status("Scanning the local network for TuxDrive shares…", False)
        _run_thread(self.controller.peers.discover, self._discovery_loaded, 4.0)

    def _discovery_loaded(self, peers: list[DiscoveredPeer] | None, error: Exception | None) -> bool:
        if error:
            self._set_status(f"LAN discovery failed: {error}", True)
            return False
        for peer in peers or []:
            self.discovery_store.append([peer.name, f"{peer.host}:{peer.port}", peer.fingerprint, peer])
        self._set_status(f"Found {len(peers or [])} local TuxDrive share(s). Verify the fingerprint before use.", False)
        return False

    def _use_discovered(self, _button: Gtk.Button) -> None:
        model, selected = self.discovery_view.get_selection().get_selected()
        if not selected:
            self._set_status("Select a discovered share first.", True)
            return
        peer = model[selected][3]
        self._apply_invitation(peer.invitation())
        self._set_status(f"Loaded {peer.name}. Confirm fingerprint {peer.fingerprint}, select a local folder, then connect.", False)

    def _save_connection(self, _button: Gtk.Button) -> None:
        try:
            folder = self.connection_folder.get_filename()
            if not folder:
                raise PeerError("Select a local folder for the synchronized copy")
            invitation = PeerInvitation(
                self.connection_name.get_text().strip() or "Peer folder",
                validate_host(self.connection_host.get_text()),
                validate_port(self.connection_port.get_value_as_int()),
                normalize_public_key(self.connection_host_key.get_text()),
                lease_minutes=self.connection_lease.get_value_as_int(),
            )
            if (
                self.loaded_invitation
                and self.loaded_invitation.host == invitation.host
                and self.loaded_invitation.host_key == invitation.host_key
            ):
                invitation.relay_host = self.loaded_invitation.relay_host
                invitation.relay_port = self.loaded_invitation.relay_port
                invitation.role = self.loaded_invitation.role
                invitation.remote_path = self.loaded_invitation.remote_path
                invitation.one_time_drop_id = self.loaded_invitation.one_time_drop_id
                invitation.expires_at = self.loaded_invitation.expires_at
            invitation.assert_usable()
            account = self._selected_connection()
            remote = account.remote if account else "peer-" + datetime.now().strftime("%H%M%S")
            candidate = remote + "-verify"
            try:
                self.controller.rclone.delete_remote(candidate)
            except Exception:
                pass
            endpoint_invitations = [invitation]
            if invitation.relay_host and invitation.relay_port:
                endpoint_invitations.append(PeerInvitation(
                    invitation.name, invitation.relay_host, invitation.relay_port,
                    invitation.host_key, invitation.share_id, invitation.lease_minutes,
                ))
            connected = None
            last_error = None
            for endpoint in endpoint_invitations:
                try:
                    self.controller.peers.configure_connection(candidate, endpoint)
                    self.controller.rclone.validate_remote(candidate)
                    connected = endpoint
                    break
                except Exception as exc:
                    last_error = exc
                finally:
                    try:
                        self.controller.rclone.delete_remote(candidate)
                    except Exception:
                        pass
            if connected is None:
                raise PeerError(f"Direct and relay endpoints failed: {last_error}")
            self.controller.peers.configure_connection(remote, connected)
            if account is None:
                account = Account(remote, Provider.PEER, invitation.name)
                self.controller.config.accounts.append(account)
                job = SyncJob(
                    account_remote=remote,
                    local_path=folder,
                    name=invitation.name,
                    cloud_location_name="Direct encrypted peer",
                    remote_path=invitation.remote_path,
                    mode=invitation.role.sync_mode,
                    peer_leases=True,
                    peer_lease_minutes=invitation.lease_minutes,
                    peer_delta=True,
                    peer_role=invitation.role,
                    one_time_drop_id=invitation.one_time_drop_id,
                )
                self.controller.config.jobs.append(job)
            else:
                job = next((item for item in self.controller.config.jobs if item.account_remote == remote), None)
                if job:
                    job.local_path = folder
                    job.name = invitation.name
                    job.initialized = False
                    job.peer_leases = True
                    job.peer_lease_minutes = invitation.lease_minutes
                    job.peer_delta = True
                    job.remote_path = invitation.remote_path
                    job.mode = invitation.role.sync_mode
                    job.peer_role = invitation.role
                    job.one_time_drop_id = invitation.one_time_drop_id
            account.display_name = invitation.name
            account.peer_host = invitation.host
            account.peer_port = invitation.port
            account.peer_host_key = invitation.host_key
            self.controller.save()
            self.controller.reconfigure_callbacks()
            if self.controller.window:
                self.controller.window.refresh()
            if job:
                self.controller.run_job(job)
            self._reload_connection_choices(remote)
            self.controller.audit.record("peer", "connection verified", "success", job_id=job.id if job else "", peer=invitation.name, path=invitation.remote_path, detail=invitation.role.label)
            self._set_status(f"Peer verified; {invitation.role.label.lower()} synchronization started.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

    def _delete_connection(self, _button: Gtk.Button) -> None:
        account = self._selected_connection()
        if not account:
            return
        for job in [item for item in self.controller.config.jobs if item.account_remote == account.remote]:
            self.controller.stop_job(job)
            self.controller.config.jobs.remove(job)
        try:
            self.controller.rclone.delete_remote(account.remote)
        except Exception:
            pass
        self.controller.config.accounts.remove(account)
        self.controller.save()
        self._reload_connection_choices()
        if self.controller.window:
            self.controller.window.refresh()
        self._set_status("Peer connection removed; local and remote files were not deleted.", False)

    def _set_status(self, message: str, error: bool) -> None:
        color = "#c01c28" if error else "#2ec27e"
        self.status.set_markup(
            f"<span foreground='{color}'>{GLib.markup_escape_text(message)}</span>"
        )


class ProfileDialog(Gtk.Dialog):
    """Encrypted, user-owned cloud profile backup and device restore."""

    def __init__(self, parent: Gtk.Window, controller: "TuxDriveApplication") -> None:
        super().__init__(title="TuxDrive Profile and device migration", transient_for=parent, modal=True)
        self.controller = controller
        self.set_default_size(650, 470)
        self.set_icon_name("tuxdrive")
        area = self.get_content_area()
        area.set_border_width(24)
        area.set_spacing(12)
        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='large' weight='bold'>Encrypted TuxDrive Profile</span>")
        area.pack_start(title, False, False, 0)
        description = Gtk.Label(xalign=0)
        description.set_line_wrap(True)
        description.set_text(
            "Link TuxDrive to one of your OAuth cloud accounts. Configuration is encrypted "
            "on this device before upload; TuxDrive operates no profile server. On a new "
            "device, connect the same provider, then restore this profile."
        )
        area.pack_start(description, False, False, 0)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        self.remote = Gtk.ComboBoxText()
        accounts = [item for item in controller.config.accounts if item.provider.browser_oauth]
        for account in accounts:
            self.remote.append(account.remote, f"{account.provider.label} · {account.display_name}")
        preferred = controller.config.settings.profile_remote
        if not (preferred and self.remote.set_active_id(preferred)) and accounts:
            self.remote.set_active(0)
        self.password = Gtk.Entry()
        self.password.set_visibility(False)
        self.password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.password.set_placeholder_text("At least 10 characters")
        self.confirm = Gtk.Entry()
        self.confirm.set_visibility(False)
        self.confirm.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.include = Gtk.CheckButton(label="Include OAuth credentials and peer private keys")
        self.include.set_tooltip_text("Sensitive: permits a full device migration, but increases the impact of a weak or lost backup password")
        for row, (label, widget) in enumerate((
            ("Profile storage account", self.remote),
            ("Backup password", self.password),
            ("Confirm password", self.confirm),
            ("Sensitive migration", self.include),
        )):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        area.pack_start(grid, False, False, 0)
        warning = Gtk.Label(xalign=0)
        warning.set_line_wrap(True)
        warning.set_markup(
            "<b>Keep the password safe.</b> It is never uploaded and cannot be recovered. "
            "Credential migration is off by default. Restoring replaces this device's TuxDrive configuration; a local pre-migration copy is retained."
        )
        area.pack_start(warning, False, False, 0)
        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(label="Ready", xalign=0)
        self.status.set_line_wrap(True)
        row = Gtk.Box(spacing=10)
        row.pack_start(self.spinner, False, False, 0)
        row.pack_start(self.status, True, True, 0)
        area.pack_start(row, False, False, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.add_button("Inspect cloud backup", 1)
        self.add_button("Restore this device", 2)
        self.add_button("Store encrypted backup", 3)
        self.connect("response", self._response)
        self.show_all()
        if not accounts:
            self._status("Connect Google Drive, OneDrive, Dropbox, Box, or pCloud first.", True)

    def _status(self, text: str, error: bool = False) -> None:
        color = "#c01c28" if error else "#2ec27e"
        self.status.set_markup(f"<span foreground='{color}'>{GLib.markup_escape_text(text)}</span>")

    def _response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response in (Gtk.ResponseType.CLOSE, Gtk.ResponseType.DELETE_EVENT):
            dialog.destroy()
            return
        remote, password = self.remote.get_active_id(), self.password.get_text()
        if not remote:
            self._status("Choose a connected OAuth account.", True)
            return
        if response == 3 and password != self.confirm.get_text():
            self._status("The backup passwords do not match.", True)
            return
        self.spinner.start()
        self.set_response_sensitive(1, False)
        self.set_response_sensitive(2, False)
        self.set_response_sensitive(3, False)
        operation = {1: self._inspect, 2: self._restore, 3: self._backup}[response]
        _run_thread(operation, self._done, remote, password)

    def _inspect(self, remote: str, password: str):
        data = self.controller.profiles.download(remote)
        return ("inspect", self.controller.profiles.summary(data, password))

    def _backup(self, remote: str, password: str):
        self.controller.config.settings.profile_remote = remote
        summary = self.controller.profiles.upload(
            remote, self.controller.config, password, self.include.get_active()
        )
        return ("backup", summary)

    def _restore(self, remote: str, password: str):
        data = self.controller.profiles.download(remote)
        summary = self.controller.profiles.summary(data, password)
        restored = self.controller.profiles.restore(
            data, password, restore_credentials=self.include.get_active()
        )
        restored.settings.profile_remote = remote
        return ("restore", summary, restored)

    def _done(self, result, error: Exception | None) -> bool:
        self.spinner.stop()
        for response in (1, 2, 3):
            self.set_response_sensitive(response, True)
        if error:
            self._status(f"Profile operation failed safely: {error}", True)
            return False
        action, summary = result[0], result[1]
        if action == "restore":
            self.controller.config = result[2]
            self.controller.rclone = RcloneClient(self.controller.config.settings.rclone_path)
            self.controller.engine = SyncEngine(self.controller.config.settings.rclone_path)
            self.controller.profiles = ProfileManager(self.controller.store, self.controller.rclone)
            self.controller.save()
            if self.controller.window:
                self.controller.window.refresh()
        elif action == "backup":
            self.controller.config.settings.profile_last_backup = summary.created_at
            self.controller.save()
        verb = "Restored" if action == "restore" else "Stored" if action == "backup" else "Found"
        secret = "includes credentials" if summary.includes_credentials else "configuration only"
        self._status(
            f"{verb} profile from {summary.device_name}, TuxDrive {summary.app_version}: "
            f"{summary.accounts} account(s), {summary.jobs} job(s), {secret}."
        )
        return False


class OperationsDashboard(Gtk.Dialog):
    def __init__(self, parent: Gtk.Window, controller: "TuxDriveApplication") -> None:
        super().__init__(title="TuxDrive sync health and audit", transient_for=parent, modal=False)
        self.set_default_size(920, 620)
        self.set_icon_name("tuxdrive")
        notebook = Gtk.Notebook()
        notebook.append_page(self._health(controller), Gtk.Label(label="Sync health"))
        notebook.append_page(self._audit(controller), Gtk.Label(label="Audit timeline"))
        notebook.append_page(self._capabilities(), Gtk.Label(label="Provider capabilities"))
        self.get_content_area().set_border_width(12)
        self.get_content_area().pack_start(notebook, True, True, 0)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda dialog, _response: dialog.destroy())
        self.show_all()

    @staticmethod
    def _tree(columns: tuple[str, ...], rows: list[tuple[str, ...]]) -> Gtk.Widget:
        store = Gtk.ListStore(*([str] * len(columns)))
        for row in rows:
            store.append(list(row))
        view = Gtk.TreeView(model=store)
        for index, title in enumerate(columns):
            renderer = Gtk.CellRendererText()
            renderer.set_property("ellipsize", 3)
            view.append_column(Gtk.TreeViewColumn(title, renderer, text=index))
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(view)
        return scroll

    def _health(self, controller: "TuxDriveApplication") -> Gtk.Widget:
        rows = []
        running, mounted, callbacks = controller.engine.running_jobs, controller.engine.mounted_jobs, controller.engine.callback_jobs
        for job in controller.config.jobs:
            state = "Synchronizing" if job.id in running else "Streaming" if job.id in mounted else "Error" if job.last_error else "Paused" if not job.enabled else "Healthy" if job.initialized else "Pending"
            callback = "Active" if job.id in callbacks else "Inactive"
            rows.append((job.name, state, job.mode.label, job.peer_role.label if job.peer_delta else "Cloud", callback, job.last_run or "Never", job.last_error or job.last_status))
        return self._tree(("Folder", "State", "Mode", "Access", "Callbacks", "Last run", "Detail"), rows)

    def _audit(self, controller: "TuxDriveApplication") -> Gtk.Widget:
        rows = [
            (event.timestamp, event.category, event.action, event.outcome, event.peer, event.path, event.detail)
            for event in controller.audit.recent(500)
        ]
        return self._tree(("Time", "Category", "Action", "Result", "Peer", "Path", "Detail"), rows)

    def _capabilities(self) -> Gtk.Widget:
        rows = []
        for provider, value in CAPABILITIES.items():
            rows.append((provider.label, "Yes" if value.streaming else "No", "Yes" if value.polling else "No", "Yes" if value.hashes else "No", "Yes" if value.server_move else "No", "Yes" if value.share_links else "No", "Yes" if value.versions else "No", value.notes))
        return self._tree(("Provider", "Streaming", "Polling", "Hashes", "Moves", "Share links", "Versions", "Notes"), rows)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application: "TuxDriveApplication") -> None:
        super().__init__(application=application, title="TuxDrive")
        self.controller = application
        self.set_default_size(920, 620)
        self.set_icon_name("tuxdrive")
        self.connect("delete-event", self._hide_instead_of_close)

        header = Gtk.HeaderBar(title="TuxDrive", subtitle="Cloud sync, streaming, and encrypted peer sharing")
        header.set_show_close_button(True)
        self.set_titlebar(header)
        brand = Gtk.Image.new_from_icon_name("tuxdrive", Gtk.IconSize.LARGE_TOOLBAR)
        brand.set_tooltip_text("TuxDrive")
        header.pack_start(brand)
        add_account = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        add_account.set_tooltip_text("Connect cloud account")
        add_account.connect("clicked", self._choose_provider)
        header.pack_start(add_account)
        peers = Gtk.Button.new_from_icon_name("network-workgroup-symbolic", Gtk.IconSize.BUTTON)
        peers.set_tooltip_text("Peer-to-peer shared folders")
        peers.connect("clicked", self._show_peer_sharing)
        header.pack_start(peers)
        health = Gtk.Button.new_from_icon_name("view-statistics-symbolic", Gtk.IconSize.BUTTON)
        health.set_tooltip_text("Sync health, peer audit timeline, and provider capabilities")
        health.connect("clicked", lambda _button: OperationsDashboard(self, self.controller))
        header.pack_start(health)
        settings = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        settings.set_tooltip_text("Settings")
        settings.connect("clicked", self._show_settings)
        header.pack_end(settings)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(root)
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        root.pack_start(content, True, True, 0)

        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.set_size_request(260, -1)
        sidebar.set_border_width(16)
        sidebar.get_style_context().add_class("sidebar")
        account_label = Gtk.Label(xalign=0)
        account_label.set_markup("<b>Cloud accounts</b>")
        sidebar.pack_start(account_label, False, False, 0)
        self.account_list = Gtk.ListBox()
        self.account_list.set_selection_mode(Gtk.SelectionMode.NONE)
        sidebar.pack_start(self.account_list, False, False, 0)
        connect_button = Gtk.Button(label="Connect account")
        connect_button.connect("clicked", self._choose_provider)
        sidebar.pack_start(connect_button, False, False, 0)
        content.pack_start(sidebar, False, False, 0)

        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main.set_border_width(20)
        heading_row = Gtk.Box(spacing=10)
        heading = Gtk.Label(xalign=0)
        heading.set_markup("<span size='large' weight='bold'>Synchronized folders</span>")
        heading_row.pack_start(heading, True, True, 0)
        add_job = Gtk.Button(label="Add folder")
        add_job.connect("clicked", self._add_job)
        heading_row.pack_end(add_job, False, False, 0)
        main.pack_start(heading_row, False, False, 0)
        self.job_list = Gtk.ListBox()
        self.job_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.job_list)
        main.pack_start(scroll, True, True, 0)

        activity = Gtk.Expander(label="Live activity log")
        activity.set_expanded(True)
        self.activity_view = Gtk.TextView()
        self.activity_view.set_editable(False)
        self.activity_view.set_cursor_visible(False)
        self.activity_view.set_monospace(True)
        self.activity_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        activity_scroll = Gtk.ScrolledWindow()
        activity_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        activity_scroll.set_size_request(-1, 190)
        activity_scroll.add(self.activity_view)
        activity.add(activity_scroll)
        main.pack_start(activity, False, True, 0)
        content.pack_start(main, True, True, 0)

        self.infobar = Gtk.InfoBar()
        self.infobar.set_no_show_all(True)
        self.info_label = Gtk.Label(xalign=0)
        self.infobar.get_content_area().add(self.info_label)
        self.infobar.connect("response", lambda bar, _response: bar.hide())
        root.pack_end(self.infobar, False, False, 0)
        self._activity_content = ""
        self.update_dialog: Gtk.Dialog | None = None
        self.update_status: Gtk.Label | None = None
        self.update_progress: Gtk.ProgressBar | None = None
        self.update_close_button: Gtk.Button | None = None
        self.update_install_button: Gtk.Button | None = None
        self._pending_update: UpdateRelease | None = None
        self._update_pulsing = False
        GLib.timeout_add_seconds(1, self._refresh_activity_log)
        self.refresh()

    def refresh(self) -> None:
        for child in self.account_list.get_children():
            self.account_list.remove(child)
        for account in self.controller.config.accounts:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=10)
            box.set_border_width(8)
            account_jobs = [
                job for job in self.controller.config.jobs if job.account_remote == account.remote
            ]
            if any(job.id in self.controller.engine.running_jobs for job in account_jobs):
                account_state = "Synchronizing"
            elif any(job.last_error for job in account_jobs):
                account_state = "Needs attention"
            else:
                account_state = "Connected"
            icon = Gtk.Image.new_from_icon_name(account.provider.icon_name, Gtk.IconSize.DND)
            icon.set_tooltip_text(f"{account.provider.label} · {account_state}")
            text = Gtk.Label(xalign=0)
            text.set_markup(
                f"<b>{GLib.markup_escape_text(account.display_name)}</b>\n"
                f"<small>{account.provider.label} · {account_state}</small>"
            )
            menu = Gtk.MenuButton()
            menu.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
            popup = Gtk.Menu()
            online = Gtk.MenuItem(label="Peer settings" if account.provider is Provider.PEER else "Open online")
            online.connect("activate", self._open_online, account)
            reconnect = Gtk.MenuItem(label="Reconnect / refresh credentials")
            reconnect.connect("activate", self._reconnect, account)
            remove = Gtk.MenuItem(label="Remove account")
            remove.connect("activate", self._remove_account, account)
            popup.append(online)
            popup.append(reconnect)
            popup.append(remove)
            popup.show_all()
            menu.set_popup(popup)
            box.pack_start(icon, False, False, 0)
            box.pack_start(text, True, True, 0)
            box.pack_end(menu, False, False, 0)
            row.add(box)
            self.account_list.add(row)

        for child in self.job_list.get_children():
            self.job_list.remove(child)
        if not self.controller.config.jobs:
            empty = Gtk.Label(
                label="Connect an account, then add a synchronized folder or virtual drive."
            )
            empty.set_margin_top(60)
            empty.get_style_context().add_class("dim-label")
            self.job_list.add(empty)
        for job in self.controller.config.jobs:
            self.job_list.add(self._job_row(job))
        self.show_all()
        self.infobar.hide()

    def _job_row(self, job: SyncJob) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        mounted = job.id in self.controller.engine.mounted_jobs
        account = next((item for item in self.controller.config.accounts if item.remote == job.account_remote), None)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(14)
        top = Gtk.Box(spacing=12)
        icon_name = account.provider.icon_name if account else "folder-remote-symbolic"
        job_icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND)
        job_icon.set_tooltip_text(account.provider.label if account else "Cloud storage")
        top.pack_start(job_icon, False, False, 0)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<b>{GLib.markup_escape_text(job.name)}</b>")
        detail = Gtk.Label(
            label=(
                f"{job.mode.label} · "
                f"{job.cloud_location_name or job.account_remote}:/{job.remote_path}"
                f"  →  {job.local_path}"
            ),
            xalign=0,
        )
        detail.set_ellipsize(3)
        status = Gtk.Label(label=job.last_status, xalign=0)
        status.get_style_context().add_class("dim-label")
        labels.pack_start(title, False, False, 0)
        labels.pack_start(detail, False, False, 0)
        labels.pack_start(status, False, False, 0)
        top.pack_start(labels, True, True, 0)
        toggle = Gtk.Switch(active=job.enabled)
        toggle.set_name("tuxdrive-job-switch")
        toggle.set_size_request(46, 26)
        toggle.set_hexpand(False)
        toggle.set_vexpand(False)
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.set_halign(Gtk.Align.END)
        toggle.set_tooltip_text("Enable automatic synchronization")
        toggle.connect("notify::active", self._toggle_job, job)
        top.pack_end(toggle, False, False, 0)
        outer.pack_start(top, False, False, 0)
        actions = Gtk.Box(spacing=8)
        sync = Gtk.Button(label=(
            "Open drive" if mounted else
            "Start streaming" if job.mode is SyncMode.VIRTUAL_DRIVE else
            "Sync now"
        ))
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            sync.set_tooltip_text(
                "Show cloud files immediately; download content only when a file is opened"
            )
        sync.connect(
            "clicked",
            lambda _button: (
                self._open_path(job.local)
                if mounted
                else self.controller.run_job(job)
            ),
        )
        cancel = Gtk.Button(
            label="Disconnect" if job.mode is SyncMode.VIRTUAL_DRIVE else "Stop"
        )
        cancel.connect("clicked", lambda _button: self.controller.stop_job(job))
        open_button = Gtk.Button(label="Open folder")
        open_button.connect("clicked", lambda _button: self._open_path(job.local))
        log_button = Gtk.Button(label="View log")
        log_button.connect("clicked", lambda _button: self._open_path(cache_home() / "tuxdrive" / "logs"))
        edit_button = Gtk.Button(label="Edit")
        edit_button.connect("clicked", self._edit_job, job)
        rename_button = Gtk.Button(label="Rename")
        rename_button.set_tooltip_text("Change only the name displayed in TuxDrive")
        rename_button.connect("clicked", self._rename_job, job)
        share_button = Gtk.Button(label="Share link")
        share_button.connect("clicked", self._share_job, job)
        share_button.set_sensitive(bool(account and capabilities_for(account.provider).share_links))
        if not share_button.get_sensitive():
            share_button.set_tooltip_text("This provider does not expose a safe share-link capability")
        history_button = Gtk.Button(label="History")
        history_button.set_tooltip_text("Restore locally retained versions and recycled files")
        history_button.connect("clicked", lambda _button: RecoveryHistoryDialog(self, self.controller, job))
        verify_button = Gtk.Button(label="Verify")
        verify_button.set_tooltip_text("Compare content and repair selected integrity differences")
        verify_button.connect("clicked", lambda _button: IntegrityDialog(self, self.controller, job))
        conflicts_button = Gtk.Button(label="Conflicts")
        conflicts_button.connect("clicked", lambda _button: IntegrityDialog(self, self.controller, job, True))
        remove = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        remove.set_tooltip_text("Remove synchronization")
        remove.connect("clicked", self._remove_job, job)
        for widget in (sync, cancel, open_button, share_button, history_button, verify_button, conflicts_button, rename_button, edit_button, log_button):
            actions.pack_start(widget, False, False, 0)
        actions.pack_end(remove, False, False, 0)
        outer.pack_start(actions, False, False, 0)
        row.add(outer)
        return row

    def _choose_provider(self, _button: Gtk.Widget) -> None:
        dialog = Gtk.Dialog(title="Connect cloud storage", transient_for=self, modal=True)
        dialog.set_default_size(560, 360)
        area = dialog.get_content_area()
        area.set_border_width(24)
        prompt = Gtk.Label(xalign=0)
        prompt.set_markup("<span size='large' weight='bold'>Choose a storage provider</span>\n<small>All providers support selective folder sync and files-on-demand mounting.</small>")
        area.pack_start(prompt, False, False, 8)
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        providers = [provider for provider in Provider if provider not in {Provider.PEER, Provider.VAULT}]
        for index, provider in enumerate(providers, start=1):
            button = Gtk.Button(label=provider.label)
            button.set_image(Gtk.Image.new_from_icon_name(provider.icon_name, Gtk.IconSize.DND))
            button.set_always_show_image(True)
            button.set_hexpand(True)
            button.connect("clicked", lambda _button, response=index: dialog.response(response))
            grid.attach(button, (index - 1) % 2, (index - 1) // 2, 1, 1)
        area.pack_start(grid, True, True, 8)
        vault_response = len(providers) + 1
        vault = Gtk.Button(label="Create encrypted vault on a connected account")
        vault.set_image(Gtk.Image.new_from_icon_name(Provider.VAULT.icon_name, Gtk.IconSize.DND))
        vault.set_always_show_image(True)
        vault.connect("clicked", lambda _button: dialog.response(vault_response))
        area.pack_start(vault, False, False, 8)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if 1 <= response <= len(providers):
            provider = providers[response - 1]
            OAuthWizard(self, self.controller.rclone, provider, self.controller.add_account)
        elif response == vault_response:
            vault_dialog = VaultDialog(self, self.controller)
            if vault_dialog.run() == Gtk.ResponseType.OK:
                try:
                    self.controller.add_account(vault_dialog.create())
                except (RcloneError, OSError) as exc:
                    self.message(f"Vault creation failed safely: {exc}", Gtk.MessageType.ERROR)
            vault_dialog.destroy()

    def _add_job(self, _button: Gtk.Widget) -> None:
        if not self.controller.config.accounts:
            self.message("Connect a cloud account first.", Gtk.MessageType.WARNING)
            return
        dialog = SyncJobDialog(self, self.controller.rclone, self.controller.config.accounts)
        if dialog.run() == Gtk.ResponseType.OK:
            jobs = dialog.jobs()
            existing_jobs = list(self.controller.config.jobs)
            if not jobs:
                self.message("Select at least one cloud folder.", Gtk.MessageType.ERROR)
            elif any(
                paths_overlap(job.local_path, item.local_path)
                and not safe_streaming_overlap(job, item)
                for job in jobs
                for item in existing_jobs
            ):
                self.message(
                    "That folder overlaps another job in an unsafe direction. A streaming drive may be an empty child folder of a normal sync job.",
                    Gtk.MessageType.ERROR,
                )
            else:
                self.controller.config.jobs.extend(jobs)
                self.controller.save()
                self.controller.reconfigure_callbacks()
                self.refresh()
                for job in jobs:
                    self.controller.run_job(job)
        dialog.destroy()

    def _toggle_job(self, switch: Gtk.Switch, _property, job: SyncJob) -> None:
        job.enabled = switch.get_active()
        self.controller.save()
        if not job.enabled:
            self.controller.stop_job(job)
        elif job.initialized:
            self.controller.start_callbacks(job)

    def _edit_job(self, _button: Gtk.Button, job: SyncJob) -> None:
        dialog = SyncJobDialog(
            self, self.controller.rclone, self.controller.config.accounts, existing=job
        )
        if dialog.run() == Gtk.ResponseType.OK:
            values = dialog.jobs()
            if not values:
                self.message("Select one cloud folder.", Gtk.MessageType.ERROR)
                dialog.destroy()
                return
            updated = values[0]
            duplicate = any(
                item.id != job.id
                and paths_overlap(item.local_path, updated.local_path)
                and not safe_streaming_overlap(updated, item)
                for item in self.controller.config.jobs
            )
            if duplicate:
                self.message(
                    "Unsafe overlap. A streaming drive may be an empty child folder of a normal sync job, but not its parent.",
                    Gtk.MessageType.ERROR,
                )
            else:
                index = self.controller.config.jobs.index(job)
                if (job.local_path, job.remote_spec, job.mode) != (
                    updated.local_path,
                    updated.remote_spec,
                    updated.mode,
                ):
                    updated.initialized = False
                self.controller.stop_job(job)
                self.controller.config.jobs[index] = updated
                self.controller.save()
                self.controller.reconfigure_callbacks()
                self.refresh()
        dialog.destroy()

    def _share_job(self, _button: Gtk.Button, job: SyncJob) -> None:
        self.message("Creating a provider share link…")
        _run_thread(self.controller.rclone.public_link, self._share_ready, job.remote_spec)

    def _share_ready(self, link: str | None, error: Exception | None) -> bool:
        if error or not link:
            self.message(str(error or "This provider could not create a link."), Gtk.MessageType.ERROR)
            return False
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(link, -1)
        self.message("Share link copied to the clipboard.")
        return False

    def _rename_job(self, _button: Gtk.Button, job: SyncJob) -> None:
        dialog = Gtk.Dialog(title="Rename synchronized folder", transient_for=self, modal=True)
        area = dialog.get_content_area()
        area.set_border_width(20)
        area.set_spacing(10)
        label = Gtk.Label(
            label="This changes only the name shown in TuxDrive. Cloud and local folder names stay unchanged.",
            xalign=0,
        )
        label.set_line_wrap(True)
        entry = Gtk.Entry()
        entry.set_text(job.name)
        entry.set_activates_default(True)
        area.pack_start(label, False, False, 0)
        area.pack_start(entry, False, False, 0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        save = dialog.add_button("Rename", Gtk.ResponseType.OK)
        save.get_style_context().add_class("suggested-action")
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            name = entry.get_text().strip()
            if name:
                job.name = name
                self.controller.save()
                self.refresh()
            else:
                self.message("The displayed name cannot be empty.", Gtk.MessageType.WARNING)
        dialog.destroy()

    def _remove_job(self, _button: Gtk.Button, job: SyncJob) -> None:
        if not self._confirm(f"Stop and remove ‘{job.name}’? Local and cloud files will not be deleted."):
            return
        self.controller.stop_job(job)
        self.controller.config.jobs.remove(job)
        self.controller.save()
        self.controller.reconfigure_callbacks()
        self.refresh()

    def _remove_account(self, _item: Gtk.MenuItem, account: Account) -> None:
        if any(job.account_remote == account.remote for job in self.controller.config.jobs):
            self.message("Remove synchronized folders using this account first.", Gtk.MessageType.WARNING)
            return
        if not self._confirm(f"Remove {account.display_name} and its local authorization?"):
            return
        try:
            self.controller.rclone.delete_remote(account.remote)
        except RcloneError as exc:
            self.message(str(exc), Gtk.MessageType.ERROR)
            return
        self.controller.config.accounts.remove(account)
        self.controller.save()
        self.refresh()

    def _open_online(self, _item: Gtk.MenuItem, account: Account) -> None:
        if account.provider is Provider.PEER:
            self._show_peer_sharing(_item)
            return
        if account.provider.home_url:
            webbrowser.open(account.provider.home_url)
        elif account.provider is Provider.VAULT:
            self.message("Encrypted vaults have no unencrypted provider website. Open the backing account only to inspect ciphertext.")
        else:
            self.message("This Nextcloud account uses its configured server URL.")

    def _reconnect(self, _item: Gtk.MenuItem, account: Account) -> None:
        if account.provider is Provider.PEER:
            self._show_peer_sharing(_item)
            return
        if account.provider is Provider.VAULT:
            self.message("Vault keys cannot be refreshed or recovered. Create a new vault to change its encryption credentials.", Gtk.MessageType.WARNING)
            return
        if not account.provider.browser_oauth:
            OAuthWizard(
                self, self.controller.rclone, account.provider,
                self.controller.add_account, existing=account,
            )
            return
        self.message("Authorization is opening in your browser…", Gtk.MessageType.INFO)
        _run_thread(self.controller.rclone.reconnect, self._reconnect_done, account.remote)

    def _reconnect_done(self, _result, error: Exception | None) -> bool:
        self.message(str(error) if error else "Account authorization refreshed.", Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO)
        return False

    def _show_settings(self, _button: Gtk.Widget) -> None:
        dialog = Gtk.Dialog(title="TuxDrive settings", transient_for=self, modal=True)
        dialog.set_icon_name("tuxdrive")
        dialog.get_content_area().set_border_width(24)
        identity = Gtk.Box(spacing=12)
        identity.pack_start(Gtk.Image.new_from_icon_name("tuxdrive", Gtk.IconSize.DIALOG), False, False, 0)
        version = Gtk.Label(xalign=0)
        version.set_markup(f"<b>TuxDrive {GLib.markup_escape_text(__version__)}</b>\n<small>Ubuntu cloud desktop client</small>")
        identity.pack_start(version, True, True, 0)
        dialog.get_content_area().pack_start(identity, False, False, 6)
        launch = Gtk.CheckButton(label="Start TuxDrive automatically after sign-in")
        launch.set_active(self.controller.config.settings.launch_at_login)
        notifications = Gtk.CheckButton(label="Show desktop notifications")
        notifications.set_active(self.controller.config.settings.notifications)
        minimized = Gtk.CheckButton(label="Start minimized")
        minimized.set_active(self.controller.config.settings.start_minimized)
        nautilus = Gtk.CheckButton(label="Enable Nautilus integration (restart Files after changing)")
        nautilus.set_active(self.controller.config.settings.nautilus_integration)
        policy = Gtk.ComboBoxText()
        policy.append("maximum", "Maximum usage (no policy limits)")
        policy.append("controlled", "Apply network, battery and schedule policies")
        policy.set_active_id(self.controller.config.settings.network_policy)
        metered = Gtk.CheckButton(label="Allow synchronization on metered networks")
        metered.set_active(self.controller.config.settings.allow_metered_networks)
        battery = Gtk.SpinButton.new_with_range(0, 100, 5)
        battery.set_value(self.controller.config.settings.pause_below_battery_percent)
        battery.set_tooltip_text("0 disables battery pausing")
        schedule_start = Gtk.Entry()
        schedule_start.set_placeholder_text("Allowed from HH:MM (blank = anytime)")
        schedule_start.set_text(self.controller.config.settings.schedule_start)
        schedule_end = Gtk.Entry()
        schedule_end.set_placeholder_text("Allowed until HH:MM")
        schedule_end.set_text(self.controller.config.settings.schedule_end)
        for widget in (launch, notifications, minimized, nautilus, policy, metered, battery, schedule_start, schedule_end):
            dialog.get_content_area().pack_start(widget, False, False, 6)
        dialog.add_button("Peer-to-peer sharing…", 3)
        dialog.add_button("TuxDrive Profile / migrate…", 4)
        dialog.add_button("Check for updates", 2)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            start_value = schedule_start.get_text().strip()
            end_value = schedule_end.get_text().strip()
            clock = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
            if bool(start_value) != bool(end_value) or any(
                value and not clock.fullmatch(value) for value in (start_value, end_value)
            ):
                dialog.destroy()
                self.message(
                    "Enter both schedule times as HH:MM (00:00–23:59), or leave both blank.",
                    Gtk.MessageType.ERROR,
                )
                return
            self.controller.config.settings.launch_at_login = launch.get_active()
            self.controller.config.settings.notifications = notifications.get_active()
            self.controller.config.settings.start_minimized = minimized.get_active()
            self.controller.config.settings.nautilus_integration = nautilus.get_active()
            self.controller.config.settings.network_policy = policy.get_active_id() or "maximum"
            self.controller.config.settings.allow_metered_networks = metered.get_active()
            self.controller.config.settings.pause_below_battery_percent = battery.get_value_as_int()
            self.controller.config.settings.schedule_start = start_value
            self.controller.config.settings.schedule_end = end_value
            self.controller.save()
            self.controller.configure_autostart()
        dialog.destroy()
        if response == 2:
            self._check_for_updates()
        elif response == 3:
            self._show_peer_sharing(_button)
        elif response == 4:
            ProfileDialog(self, self.controller)

    def _show_peer_sharing(self, _button: Gtk.Widget) -> None:
        PeerSharingDialog(self, self.controller)

    def _check_for_updates(self) -> None:
        if self.update_dialog:
            self.update_dialog.present()
            return
        dialog = Gtk.Dialog(title="TuxDrive update", transient_for=self, modal=True)
        dialog.set_icon_name("tuxdrive")
        dialog.set_default_size(520, 210)
        area = dialog.get_content_area()
        area.set_border_width(24)
        area.set_spacing(14)
        title = Gtk.Label(xalign=0)
        title.set_markup(f"<span size='large' weight='bold'>Checking for updates</span>\n<small>Installed version: {GLib.markup_escape_text(__version__)}</small>")
        status = Gtk.Label(label="Contacting the TuxDrive release repository…", xalign=0)
        status.set_line_wrap(True)
        progress = Gtk.ProgressBar()
        progress.set_show_text(True)
        progress.set_text("Checking…")
        area.pack_start(title, False, False, 0)
        area.pack_start(status, False, False, 0)
        area.pack_start(progress, False, False, 0)
        self.update_install_button = dialog.add_button("Download and install", Gtk.ResponseType.OK)
        self.update_install_button.set_sensitive(False)
        self.update_close_button = dialog.add_button("Close", Gtk.ResponseType.CANCEL)
        self.update_close_button.set_sensitive(False)
        dialog.connect("response", self._update_dialog_response)
        self.update_dialog = dialog
        self.update_status = status
        self.update_progress = progress
        self._pending_update = None
        self._update_pulsing = True
        GLib.timeout_add(120, self._pulse_update_progress)
        dialog.show_all()
        _run_thread(self.controller.updater.check, self._update_checked)

    def _pulse_update_progress(self) -> bool:
        if not self.update_dialog or not self._update_pulsing or not self.update_progress:
            return False
        self.update_progress.pulse()
        return True

    def _update_dialog_response(self, dialog: Gtk.Dialog, response: int) -> None:
        if response == Gtk.ResponseType.OK and self._pending_update:
            release = self._pending_update
            self._pending_update = None
            self.update_install_button.set_sensitive(False)
            self.update_close_button.set_sensitive(False)
            self._update_pulsing = False
            self.update_progress.set_fraction(0)
            self.update_progress.set_text("Downloading…")
            self.update_status.set_text(f"Downloading TuxDrive {release.version} from the repository…")
            _run_thread(
                self.controller.updater.download,
                self._update_downloaded,
                release,
                self._report_update_download,
            )
            return
        self._destroy_update_dialog()

    def _destroy_update_dialog(self) -> None:
        self._update_pulsing = False
        if self.update_dialog:
            self.update_dialog.destroy()
        self.update_dialog = None
        self.update_status = None
        self.update_progress = None
        self.update_close_button = None
        self.update_install_button = None
        self._pending_update = None

    def _report_update_download(self, received: int, total: int) -> None:
        GLib.idle_add(self._apply_update_download_progress, received, total)

    def _apply_update_download_progress(self, received: int, total: int) -> bool:
        if not self.update_progress:
            return False
        if total > 0:
            fraction = min(1.0, received / total)
            self.update_progress.set_fraction(fraction)
            self.update_progress.set_text(f"Downloading… {fraction:.0%}")
        else:
            self.update_progress.pulse()
            self.update_progress.set_text(f"Downloaded {received / 1024:.0f} KiB")
        return False

    def _update_checked(self, release: UpdateRelease | None, error: Exception | None) -> bool:
        if error:
            self._update_pulsing = False
            self.update_progress.set_fraction(0)
            self.update_progress.set_text("Check failed")
            self.update_status.set_text(f"Update check failed: {error}")
            self.update_close_button.set_sensitive(True)
            return False
        if release is None:
            self._update_pulsing = False
            self.update_progress.set_fraction(1)
            self.update_progress.set_text("Up to date")
            self.update_status.set_text(f"TuxDrive {__version__} is the newest available version.")
            self.update_close_button.set_sensitive(True)
            return False
        self._update_pulsing = False
        self._pending_update = release
        self.update_progress.set_fraction(1)
        self.update_progress.set_text(f"Version {release.version} available")
        self.update_status.set_text(
            f"{release.notes or 'A newer TuxDrive release is available.'}\n\n"
            "Select Download and install to verify and install it."
        )
        self.update_install_button.set_sensitive(True)
        self.update_close_button.set_sensitive(True)
        return False

    def _update_downloaded(self, package: Path | None, error: Exception | None) -> bool:
        if error or package is None:
            self.update_progress.set_fraction(0)
            self.update_progress.set_text("Download failed")
            self.update_status.set_text(f"Update download or verification failed: {error}")
            self.update_close_button.set_sensitive(True)
            return False
        self._update_pulsing = True
        GLib.timeout_add(120, self._pulse_update_progress)
        self.update_progress.set_text("Installing…")
        self.update_status.set_text("Package verified. Approve Ubuntu's system authorization prompt to install it…")
        _run_thread(self.controller.updater.install, self._update_installed, package)
        return False

    def _update_installed(self, _result, error: Exception | None) -> bool:
        if error:
            self.update_progress.set_fraction(0)
            self.update_progress.set_text("Installation failed")
            self.update_status.set_text(f"Update installation failed: {error}")
        else:
            self.update_progress.set_fraction(1)
            self.update_progress.set_text("Update installed")
            self.update_status.set_text("TuxDrive was updated successfully. Restart the app to use the new version.")
        self._update_pulsing = False
        self.update_close_button.set_sensitive(True)
        return False

    def message(self, text: str, kind: Gtk.MessageType = Gtk.MessageType.INFO) -> None:
        self.infobar.set_message_type(kind)
        self.info_label.set_text(text)
        self.infobar.show_all()

    def prompt_blocked_google_file(self, job: SyncJob, blocked_path: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Google blocked a file as suspected malware or spam",
        )
        dialog.format_secondary_text(
            f"{blocked_path}\n\n"
            "The recommended action is to exclude this file. Only allow the download "
            "if you trust its origin and accept the malware risk."
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Allow unsafe download and retry", 2)
        recommended = dialog.add_button("Exclude file and retry", 1)
        recommended.get_style_context().add_class("suggested-action")
        response = dialog.run()
        dialog.destroy()
        if response == 1:
            rule = f"/{blocked_path.lstrip('/')}"
            if rule not in job.exclude_patterns:
                job.exclude_patterns.append(rule)
            job.acknowledge_google_abuse = False
        elif response == 2:
            job.acknowledge_google_abuse = True
        else:
            return
        job.initialized = False
        job.enabled = True
        job.last_error = ""
        job.last_status = "Recovery synchronization queued…"
        self.controller.save()
        self.refresh()
        self.controller.run_job(job)

    def _refresh_activity_log(self) -> bool:
        sources = [application_log_path()]
        sync_directory = cache_home() / "tuxdrive" / "logs"
        if sync_directory.exists():
            sources.extend(
                sorted(sync_directory.glob("*.log"), key=lambda item: item.stat().st_mtime)[-3:]
            )
        sections: list[str] = []
        for source in sources:
            content = self._tail_file(source)
            if content:
                sections.append(f"── {source.name} ──\n{content.strip()}")
        combined = "\n\n".join(sections) or "No activity recorded yet."
        if combined != self._activity_content:
            self._activity_content = combined
            buffer = self.activity_view.get_buffer()
            buffer.set_text(combined)
            self.activity_view.scroll_to_iter(buffer.get_end_iter(), 0.0, False, 0.0, 1.0)
        return True

    @staticmethod
    def _tail_file(path: Path, limit: int = 32 * 1024) -> str:
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - limit))
                data = handle.read()
            if size > limit:
                data = data.split(b"\n", 1)[-1]
            return data.decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _confirm(self, text: str) -> bool:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=text,
        )
        result = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        return result

    @staticmethod
    def _open_path(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(_desktop_open_command(str(path)), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _hide_instead_of_close(self, *_args) -> bool:
        self.hide()
        self.controller.notify("TuxDrive is still running", "Synchronization continues in the background.")
        return True


class TuxDriveApplication(Gtk.Application):
    def __init__(self, background: bool = False) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option(
            "open-online", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
            "Open the cloud location corresponding to a local TuxDrive path", "PATH",
        )
        for name, description in (
            ("offline-path", "Keep a streaming item available offline"),
            ("online-only-path", "Release a streaming item's cached content"),
        ):
            self.add_main_option(name, 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING, description, "PATH")
        self.updater = UpdateManager(__version__)
        self.background = background
        self.store = ConfigStore()
        try:
            self.config = self.store.load()
        except RuntimeError:
            self.config = AppConfig()
        self.rclone = RcloneClient(self.config.settings.rclone_path)
        self.engine = SyncEngine(self.config.settings.rclone_path)
        self.audit = AuditTimeline()
        self.peers = PeerManager(self.config.settings.rclone_path, audit=self.audit)
        self.profiles = ProfileManager(self.store, self.rclone)
        self.window: MainWindow | None = None
        self.indicator = None
        self._runtime_ready_once = False
        self._pending_nautilus_paths: list[str] = []
        self._pending_nautilus_online: list[str] = []
        self._pending_offline_requests: list[tuple[str, bool]] = []
        self._nautilus_active_jobs: set[str] = set()
        self._last_started: dict[str, datetime] = {}
        self._mount_failures: dict[str, list[datetime]] = {}

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.hold()
        LOGGER.info("GTK application startup completed")
        host_report = inspect_host()
        for line in format_report(host_report).splitlines():
            LOGGER.info("Host capability: %s", line)
        recovered = set(self.engine.recover_stale_mounts(self.config.jobs))
        for job in self.config.jobs:
            if job.id in recovered:
                job.last_status = "Recovered a disconnected files-on-demand mount; reconnecting…"
                LOGGER.warning("Detached stale streaming mount: %s", job.local_path)
        if recovered:
            self.save()
        self._install_css()
        GLib.timeout_add_seconds(30, self._scheduler_tick)
        self.configure_autostart()
        self._create_indicator()
        for name, callback in (
            ("show-path", self._nautilus_show_path),
            ("sync-path", self._nautilus_sync_path),
            ("open-online-path", self._nautilus_open_online),
            ("open-logs", self._nautilus_open_logs),
        ):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", callback)
            self.add_action(action)
        self._publish_nautilus_state()

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MainWindow(self)
            self.window.message("Preparing the cloud transfer engine…")
            _run_thread(self._load_runtime, self._runtime_loaded)
        tray_available = self.indicator is not None
        if not (tray_available and (self.background or self.config.settings.start_minimized)):
            self.window.show_all()
            self.window.present()
        self.background = False
        LOGGER.info("Application activated; window_visible=%s", self.window.get_visible())

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Receive Nautilus requests in the primary application instance."""
        arguments = list(command_line.get_arguments())[1:]
        options = command_line.get_options_dict()
        for name, available in (("offline-path", True), ("online-only-path", False)):
            selected = options.lookup_value(name, GLib.VariantType.new("s"))
            if selected is not None:
                value = selected.get_string()
                LOGGER.info("Received Nautilus offline-state request: %s available=%s", value, available)
                if self.window is None:
                    self.background = True
                    self.activate()
                if self._runtime_ready_once:
                    self._set_offline_path(value, available)
                else:
                    self._pending_offline_requests.append((value, available))
                return 0
        option = options.lookup_value(
            "open-online", GLib.VariantType.new("s")
        )
        if option is not None or "--open-online" in arguments:
            if option is not None:
                value = option.get_string()
            else:
                index = arguments.index("--open-online")
                if index + 1 >= len(arguments):
                    LOGGER.error("Nautilus online-folder request had no local path")
                    return 2
                value = arguments[index + 1]
            LOGGER.info("Received Nautilus online/cloud request: %s", value)
            if self.window is None:
                self.background = True
                self.activate()
            if self._runtime_ready_once:
                self._open_online_path(value)
            else:
                self._pending_nautilus_online.append(value)
            return 0
        self.activate()
        return 0

    def _set_offline_path(self, value: str, available: bool) -> None:
        job = self._job_for_local_path(value)
        if not job or job.mode is not SyncMode.VIRTUAL_DRIVE:
            LOGGER.warning("Offline-state request is not inside a streaming drive: %s", value)
            return
        try:
            relative = Path(value).expanduser().resolve(strict=False).relative_to(job.local.resolve(strict=False)).as_posix()
        except (OSError, RuntimeError, ValueError):
            return
        _run_thread(self.engine.set_offline, self._offline_state_ready, job, relative, available)

    def _offline_state_ready(self, result: str | None, error: Exception | None) -> bool:
        if error:
            LOGGER.error("Could not change offline availability: %s", error)
        else:
            LOGGER.info("Offline availability changed: %s", result)
            self.save()
        if self.window:
            self.window.message(str(error) if error else str(result), Gtk.MessageType.ERROR if error else Gtk.MessageType.INFO)
        return False

    def _job_for_local_path(self, value: str) -> SyncJob | None:
        try:
            selected = Path(value).expanduser().resolve(strict=False)
        except (OSError, RuntimeError):
            return None
        matches: list[tuple[int, SyncJob]] = []
        for job in self.config.jobs:
            try:
                selected.relative_to(job.local.resolve(strict=False))
                matches.append((len(job.local.parts), job))
            except (OSError, RuntimeError, ValueError):
                continue
        return max(matches, default=(0, None), key=lambda item: item[0])[1]

    def _nautilus_show_path(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        self.activate()
        value = parameter.get_string()
        job = self._job_for_local_path(value)
        if self.window:
            self.window.message(
                f"{job.name}: {job.last_status}" if job else "That path is not part of an enabled TuxDrive folder.",
                Gtk.MessageType.INFO if job else Gtk.MessageType.WARNING,
            )

    def _nautilus_sync_path(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        value = parameter.get_string()
        self.activate()
        if not self._runtime_ready_once:
            self._pending_nautilus_paths.append(value)
            if self.window:
                self.window.message("Preparing TuxDrive, then synchronization will start…")
            return
        job = self._job_for_local_path(value)
        if not job or not job.enabled:
            if self.window:
                self.window.message("That path is not part of an enabled TuxDrive folder.", Gtk.MessageType.WARNING)
            return
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            if self.window:
                self.window.message("This is a files-on-demand drive; opening a file streams its content.")
            return
        self.run_job(job)

    def _nautilus_open_logs(self, _action: Gio.SimpleAction, _parameter: GLib.Variant) -> None:
        MainWindow._open_path(log_directory())

    def _nautilus_open_online(self, _action: Gio.SimpleAction, parameter: GLib.Variant) -> None:
        value = parameter.get_string()
        if not self._runtime_ready_once:
            self._pending_nautilus_online.append(value)
            LOGGER.info("Queued online/cloud location while runtime initializes: %s", value)
            return
        self._open_online_path(value)

    def _open_online_path(self, value: str) -> None:
        job = self._job_for_local_path(value)
        if not job:
            if self.window:
                self.window.message("That path is not part of a TuxDrive folder.", Gtk.MessageType.WARNING)
            return
        account = next((item for item in self.config.accounts if item.remote == job.account_remote), None)
        if not account or account.provider in {Provider.PEER, Provider.VAULT}:
            if self.window:
                self.window.message("This peer or encrypted-vault path has no safe provider web page.", Gtk.MessageType.WARNING)
            return
        try:
            local_root = Path(os.path.abspath(os.path.expanduser(job.local_path)))
            selected = Path(os.path.abspath(os.path.expanduser(value)))
            relative = selected.relative_to(local_root)
        except (OSError, ValueError):
            relative = Path()
        remote_path = "/".join(
            part for part in (job.remote_path.strip("/"), relative.as_posix().strip("/"))
            if part and part != "."
        )
        remote = job.remote_scope or job.account_remote
        remote_spec = f"{remote}:{remote_path}" if remote_path else f"{remote}:"
        if self.window:
            self.window.message("Locating the corresponding provider page…")
        _run_thread(self.rclone.online_url, self._online_url_ready, remote_spec, account.provider)

    def _online_url_ready(self, result: tuple[str, bool] | None, error: Exception | None) -> bool:
        if error or not result or not result[0]:
            if self.window:
                self.window.message(
                    str(error or "This provider does not expose a safe web-folder URL."),
                    Gtk.MessageType.WARNING,
                )
            return False
        url, exact = result
        LOGGER.info("Launching online/cloud location: %s", url)
        _run_thread(self._launch_online_url, self._online_launch_ready, url, exact)
        return False

    @staticmethod
    def _launch_online_url(url: str, exact: bool) -> tuple[bool, str]:
        """Launch through the freedesktop handler and return a checked result."""
        result = subprocess.run(
            _desktop_open_command(url),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(detail or f"desktop opener exited with status {result.returncode}")
        return exact, url

    def _online_launch_ready(
        self, result: tuple[bool, str] | None, error: Exception | None
    ) -> bool:
        if error or not result:
            detail = str(error or "The desktop URL handler did not return a result.")
            LOGGER.error("Could not open online/cloud location: %s", detail)
            notification = Gio.Notification.new("Could not open online/cloud folder")
            notification.set_body(detail)
            self.send_notification("online-folder-error", notification)
            if self.window:
                self.window.message(f"Could not open the default web browser: {detail}", Gtk.MessageType.ERROR)
            return False
        exact, url = result
        LOGGER.info("Desktop browser accepted online/cloud location: %s", url)
        if self.window:
            self.window.message(
                "Opened the matching online item."
                if exact else
                "This provider cannot address that exact path safely; opened the account root instead."
            )
        return False

    def _publish_nautilus_state(self) -> None:
        target = cache_home() / "tuxdrive" / "nautilus-state.json"
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        mounted = self.engine.mounted_jobs
        payload: dict[str, dict[str, str]] = {}
        for job in self.config.jobs:
            state = (
                "syncing" if job.id in self._nautilus_active_jobs else
                "streaming" if job.id in mounted else
                "error" if job.last_error else
                "paused" if not job.enabled or job.last_status == "Stopped" else
                "synced" if job.initialized else "pending"
            )
            payload[job.id] = {"state": state, "detail": job.last_status or state.title()}
        descriptor, temporary = tempfile.mkstemp(
            prefix="nautilus-state-", suffix=".json", dir=target.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
                handle.write("\n")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def add_account(self, account: Account) -> None:
        self.config.accounts = [item for item in self.config.accounts if item.remote != account.remote]
        self.config.accounts.append(account)
        self.save()
        if self.window:
            self.window.refresh()
            self.window.message(f"{account.display_name} connected successfully.")
        if account.provider.browser_oauth:
            _run_thread(self.profiles.available, self._profile_checked, account.remote)

    def _profile_checked(self, available: bool | None, error: Exception | None) -> bool:
        if available and not error and self.window:
            self.window.message(
                "An encrypted TuxDrive Profile is available. Open Settings → TuxDrive Profile / migrate to inspect or restore it.",
                Gtk.MessageType.INFO,
            )
        return False

    def run_job(self, job: SyncJob, quiet: bool = False) -> None:
        self.engine.configure_jobs(self.config.jobs)
        if not job.enabled and not quiet:
            job.enabled = True
        if job.id in self.engine.running_jobs:
            if self.window and not quiet:
                self.window.message(f"{job.name} is already synchronizing.")
            return
        decision = TransferPolicy(self.config.settings).evaluate()
        if not decision.allowed:
            job.last_status = decision.reason
            LOGGER.info("Policy deferred job %s: %s", job.id, decision.reason)
            self.audit.record("sync", "policy deferred", "paused", job_id=job.id, detail=decision.reason)
            self._publish_nautilus_state()
            if self.window and not quiet:
                self.window.message(decision.reason, Gtk.MessageType.INFO)
            return
        self.engine.stop_callbacks(job.id)
        job.last_status = (
            "Connecting files-on-demand drive…"
            if job.mode is SyncMode.VIRTUAL_DRIVE
            else "Synchronizing…"
        )
        LOGGER.info(
            "Starting job %s (%s): %s -> %s",
            job.id,
            job.name,
            job.remote_spec,
            job.local_path,
        )
        self.audit.record("sync", "job started", "running", job_id=job.id, path=job.remote_path, detail=job.mode.label)
        self._set_tray_state("syncing", job.name)
        self._last_started[job.id] = datetime.now(timezone.utc)
        self._nautilus_active_jobs.add(job.id)
        self._publish_nautilus_state()
        if self.window:
            self.window.refresh()
        started = self.engine.run_async(job, self._job_finished)
        if not started:
            self._nautilus_active_jobs.discard(job.id)
            self._publish_nautilus_state()
        if not started and self.window and not quiet:
            self.window.message("The job could not be started.", Gtk.MessageType.WARNING)

    def stop_job(self, job: SyncJob) -> None:
        self.engine.stop_callbacks(job.id)
        stopped = self.engine.stop_mount(job) if job.mode is SyncMode.VIRTUAL_DRIVE else self.engine.cancel(job.id)
        if stopped:
            self._nautilus_active_jobs.discard(job.id)
            job.last_status = "Stopped"
            self.audit.record("sync", "job stopped", "success", job_id=job.id, detail=job.name)
            self.save()
            if self.window:
                self.window.refresh()

    def _job_finished(self, result: JobResult) -> None:
        GLib.idle_add(self._apply_job_result, result)

    def _apply_job_result(self, result: JobResult) -> bool:
        job = next((item for item in self.config.jobs if item.id == result.job_id), None)
        if not job:
            return False
        self._nautilus_active_jobs.discard(job.id)
        now = datetime.now(timezone.utc)
        job.last_run = now.isoformat()
        job.last_status = result.message
        job.last_error = "" if result.success else result.message
        if result.requires_resync:
            job.initialized = False
            job.enabled = False
            job.last_status = f"{result.message} Automatic sync paused; recovery sync required."
            job.last_error = job.last_status
        if result.mass_change_blocked:
            job.enabled = False
            job.last_status = f"{result.message} Review the log, then re-enable the job to approve a later retry."
            job.last_error = job.last_status
        if result.success and job.mode is not SyncMode.VIRTUAL_DRIVE:
            job.initialized = True
        self._set_tray_state("ready" if result.success else "error", result.message)
        LOGGER.info("Job %s finished: success=%s message=%s", job.id, result.success, result.message)
        account = next((item for item in self.config.accounts if item.remote == job.account_remote), None)
        self.audit.record(
            "peer" if job.peer_delta else "sync",
            "incremental transfer" if result.incremental else "synchronization",
            "success" if result.success else "failed",
            job_id=job.id,
            peer=account.display_name if account and account.provider is Provider.PEER else "",
            path=job.remote_path,
            detail=result.message,
        )
        if result.success and job.one_time_drop_id:
            job.enabled = False
            job.last_status = "One-time file drop sent; invitation retired"
            self.audit.record("peer", "one-time drop sent", "success", job_id=job.id, path=job.remote_path)
        self.save()
        if result.success and not result.incremental:
            self.start_callbacks(job)
        if result.mount_lost and job.enabled:
            recent = self._mount_failures.setdefault(job.id, [])
            cutoff = now.timestamp() - 300
            recent[:] = [item for item in recent if item.timestamp() >= cutoff]
            recent.append(now)
            if len(recent) <= 3:
                delay = 3 * len(recent)
                job.last_status = f"Streaming drive disconnected; retrying in {delay} seconds…"
                self.save()
                GLib.timeout_add_seconds(delay, self._retry_mount, job.id)
        if self.window:
            self.window.refresh()
            if not result.success:
                if result.blocked_path:
                    self.window.prompt_blocked_google_file(job, result.blocked_path)
                else:
                    self.window.message(f"{job.name}: {job.last_status}", Gtk.MessageType.ERROR)
        if not result.incremental or not result.success:
            self.notify(job.name, result.message)
        return False

    def _retry_mount(self, job_id: str) -> bool:
        job = next((item for item in self.config.jobs if item.id == job_id), None)
        if job and job.enabled and job.mode is SyncMode.VIRTUAL_DRIVE:
            self.run_job(job, quiet=True)
        return False

    def start_callbacks(self, job: SyncJob) -> None:
        self.engine.configure_jobs(self.config.jobs)
        self.engine.start_callbacks(
            job,
            self._job_finished,
            lambda item: GLib.idle_add(self.run_job, item, True),
        )

    def reconfigure_callbacks(self) -> None:
        self.engine.configure_jobs(self.config.jobs)
        for item in self.config.jobs:
            self.engine.stop_callbacks(item.id)
        for item in self.config.jobs:
            if (
                item.enabled
                and item.initialized
                and item.realtime_sync
                and item.mode is not SyncMode.VIRTUAL_DRIVE
            ):
                self.engine.start_callbacks(
                    item,
                    self._job_finished,
                    lambda changed: GLib.idle_add(self.run_job, changed, True),
                )

    def _scheduler_tick(self) -> bool:
        now = datetime.now(timezone.utc)
        for job in self.config.jobs:
            if not job.enabled or job.mode is SyncMode.VIRTUAL_DRIVE or job.id in self.engine.running_jobs:
                continue
            baseline = self._last_started.get(job.id)
            if baseline is None and job.last_run:
                try:
                    baseline = datetime.fromisoformat(job.last_run)
                except ValueError:
                    baseline = None
            if baseline is None or (now - baseline).total_seconds() >= job.interval_minutes * 60:
                self.run_job(job, quiet=True)
        return True

    def _create_indicator(self) -> None:
        if AyatanaAppIndicator3 is None:
            LOGGER.error("AyatanaAppIndicator3 is unavailable; tray icon cannot be created")
            return
        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "tuxdrive",
            "tuxdrive",
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_title("TuxDrive")
        self.indicator.set_icon_theme_path("/usr/share/icons/hicolor/scalable/apps")
        self.indicator.set_icon_full("tuxdrive", "TuxDrive is running")
        self.indicator.set_attention_icon_full("tuxdrive-error", "TuxDrive needs attention")
        menu = Gtk.Menu()
        show = Gtk.MenuItem(label="Open TuxDrive")
        show.connect("activate", lambda _item: self.activate())
        sync_all = Gtk.MenuItem(label="Synchronize all now")
        sync_all.connect(
            "activate",
            lambda _item: [self.run_job(job) for job in self.config.jobs if job.enabled],
        )
        pause_all = Gtk.CheckMenuItem(label="Pause all synchronization")

        def toggle_pause(item: Gtk.CheckMenuItem) -> None:
            paused = item.get_active()
            for job in self.config.jobs:
                job.enabled = not paused
                if paused:
                    self.stop_job(job)
            self.save()
            if self.window:
                self.window.refresh()

        pause_all.connect("toggled", toggle_pause)
        logs = Gtk.MenuItem(label="Open diagnostic logs")
        logs.connect("activate", lambda _item: MainWindow._open_path(log_directory()))
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _item: self.quit())
        for item in (show, sync_all, pause_all, logs, Gtk.SeparatorMenuItem(), quit_item):
            menu.append(item)
        menu.show_all()
        self.indicator.set_menu(menu)
        LOGGER.info("Tray indicator initialized")
        GLib.timeout_add_seconds(
            2,
            lambda: (self.notify("TuxDrive loaded", "Cloud synchronization is running in the tray"), False)[1],
        )

    def _set_tray_state(self, state: str, detail: str = "") -> None:
        if not self.indicator or AyatanaAppIndicator3 is None:
            return
        icon = {
            "ready": "tuxdrive",
            "syncing": "tuxdrive-sync",
            "error": "tuxdrive-error",
        }.get(state, "tuxdrive")
        self.indicator.set_icon_full(icon, f"TuxDrive: {detail or state}")
        self.indicator.set_status(
            AyatanaAppIndicator3.IndicatorStatus.ATTENTION
            if state == "error"
            else AyatanaAppIndicator3.IndicatorStatus.ACTIVE
        )

    def save(self) -> None:
        self.store.save(self.config)
        self._publish_nautilus_state()

    def notify(self, title: str, body: str) -> None:
        if not self.config.settings.notifications:
            return
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        self.send_notification(None, notification)

    def configure_autostart(self) -> None:
        if platform.system() == "Darwin":
            target = Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"
            if self.config.settings.launch_at_login:
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = {
                    "Label": APP_ID,
                    "ProgramArguments": [
                        "/Applications/TuxDrive.app/Contents/MacOS/tuxdrive", "--background"
                    ],
                    "RunAtLoad": True,
                    "ProcessType": "Interactive",
                }
                target.write_bytes(plistlib.dumps(payload))
            elif target.exists():
                target.unlink()
            return
        target = Path.home() / ".config" / "autostart" / "tuxdrive.desktop"
        if self.config.settings.launch_at_login:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = (
                "[Desktop Entry]\nType=Application\nName=TuxDrive\n"
                "Exec=tuxdrive --background\nIcon=tuxdrive\n"
                "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n"
            )
            target.write_text(content, encoding="utf-8")
        elif target.exists():
            target.unlink()

    def _load_runtime(self) -> dict[str, Provider]:
        executable = self.rclone.ensure_available()
        self.engine.rclone_path = executable
        LOGGER.info("Cloud transfer engine ready: %s", executable)
        return self.rclone.discover_accounts()

    def _runtime_loaded(
        self, existing: dict[str, Provider] | None, error: Exception | None
    ) -> bool:
        if error:
            LOGGER.error(
                "Runtime initialization failed",
                exc_info=(type(error), error, error.__traceback__),
            )
            self._set_tray_state("error", "Runtime initialization failed")
            if self.window:
                self.window.message(
                    f"Runtime preparation failed: {error}. Logs: {crash_log_path()}",
                    Gtk.MessageType.ERROR,
                )
            return False
        existing = existing or {}
        known = {account.remote for account in self.config.accounts}
        for remote, provider in existing.items():
            if remote not in known:
                self.config.accounts.append(Account(remote, provider, remote))
        self.save()
        if self.window:
            self.window.refresh()
            self.window.message("TuxDrive loaded and is running in the tray.")
        profile_accounts = [item for item in self.config.accounts if item.provider.browser_oauth]
        if profile_accounts:
            preferred = self.config.settings.profile_remote
            account = next((item for item in profile_accounts if item.remote == preferred), profile_accounts[0])
            _run_thread(self.profiles.available, self._profile_checked, account.remote)
        self._set_tray_state("ready", "Loaded")
        if not self._runtime_ready_once:
            self._runtime_ready_once = True
            for share in self.config.peer_shares:
                if share.enabled:
                    try:
                        self.peers.start(share)
                        share.last_status = f"Listening on TCP {share.port}"
                    except Exception as exc:
                        share.last_status = f"Could not start: {exc}"
                        LOGGER.error("Peer share %s failed: %s", share.id, exc)
            self.peers.start_discovery()
            self.save()
            for job in self.config.jobs:
                if job.enabled and job.mode is SyncMode.VIRTUAL_DRIVE:
                    self.run_job(job, quiet=True)
                elif job.enabled and job.initialized and job.realtime_sync:
                    self.start_callbacks(job)
            pending, self._pending_nautilus_paths = self._pending_nautilus_paths, []
            started_jobs: set[str] = set()
            for value in pending:
                job = self._job_for_local_path(value)
                if job and job.id not in started_jobs and job.enabled and job.mode is not SyncMode.VIRTUAL_DRIVE:
                    started_jobs.add(job.id)
                    self.run_job(job)
            pending_online, self._pending_nautilus_online = self._pending_nautilus_online, []
            for value in pending_online:
                self._open_online_path(value)
            pending_offline, self._pending_offline_requests = self._pending_offline_requests, []
            for value, available in pending_offline:
                self._set_offline_path(value, available)
        return False

    @staticmethod
    def _install_css() -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b".sidebar { background: @theme_base_color; border-right: 1px solid alpha(@theme_fg_color, .12); }"
            b"list row { border-bottom: 1px solid alpha(@theme_fg_color, .10); }"
            b"switch#tuxdrive-job-switch { min-width: 42px; min-height: 22px; padding: 0; margin: 0; }"
            b"switch#tuxdrive-job-switch slider { min-width: 18px; min-height: 18px; margin: 2px; padding: 0; }"
        )
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def do_shutdown(self) -> None:
        LOGGER.info("TuxDrive shutting down")
        self.peers.shutdown()
        self.engine.shutdown()
        self.release()
        Gtk.Application.do_shutdown(self)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TuxDrive cloud synchronization client")
    parser.add_argument("--background", action="store_true", help="start without opening the main window")
    parser.add_argument("--version", action="store_true", help="show version and exit")
    parser.add_argument("--diagnostics", action="store_true", help="show diagnostic log locations and exit")
    args, gtk_args = parser.parse_known_args(argv)
    if args.version:
        print(f"TuxDrive {__version__}")
        return 0
    if args.diagnostics:
        print(f"Application log: {application_log_path()}")
        print(f"Crash log: {crash_log_path()}")
        return 0
    application = TuxDriveApplication(background=args.background)
    return application.run([sys.argv[0], *gtk_args])


if __name__ == "__main__":
    raise SystemExit(main())
