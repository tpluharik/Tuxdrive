from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
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

from .config import ConfigStore, cache_home
from .engine import JobResult, SyncEngine
from .models import (
    Account, AppConfig, ConflictPolicy, PeerShare, Provider, SyncJob, SyncMode,
    paths_overlap, safe_streaming_overlap,
)
from .peer import PeerError, PeerInvitation, PeerManager, normalize_public_key, validate_host, validate_port
from .rclone import ConfigQuestion, ConfigResult, DriveLocation, RcloneClient, RcloneError
from .updater import UpdateManager, UpdateRelease

try:  # Ubuntu's AppIndicator extension provides Windows-like tray controls.
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3
except (ImportError, ValueError):  # pragma: no cover - optional desktop component
    AyatanaAppIndicator3 = None


APP_ID = "io.github.tuxdrive.TuxDrive"


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
        self.interval = Gtk.SpinButton.new_with_range(1, 1440, 1)
        self.interval.set_value(existing.interval_minutes if existing else 5)
        self.realtime_sync = Gtk.CheckButton(
            label="Sync saved file changes immediately (incremental)"
        )
        self.realtime_sync.set_active(existing.realtime_sync if existing else True)
        self.realtime_sync.set_tooltip_text(
            "Watches local saves and polls provider changes; transfers only changed paths."
        )
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
            ("Sync interval (minutes)", self.interval),
            ("Real-time callbacks", self.realtime_sync),
            ("Conflict handling", self.conflict),
            ("Maximum deletions per run", self.max_delete),
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
                conflict_policy=ConflictPolicy(self.conflict.get_active_id()),
                max_delete=self.max_delete.get_value_as_int(),
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
            return [value]
        return values

    def _account_changed(self, combo: Gtk.ComboBoxText) -> None:
        remote = combo.get_active_id()
        if remote:
            self._load_locations()

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


class PeerSharingDialog(Gtk.Dialog):
    """Manage direct encrypted folders and connections without an intermediary."""

    def __init__(self, parent: Gtk.Window, controller: "TuxDriveApplication") -> None:
        super().__init__(title="Peer-to-peer shared folders", transient_for=parent, modal=True)
        self.set_icon_name("tuxdrive")
        self.set_default_size(760, 680)
        self.controller = controller
        area = self.get_content_area()
        area.set_border_width(20)
        area.set_spacing(12)
        explanation = Gtk.Label(
            label=(
                "TuxDrive connects the two computers directly over encrypted SFTP. "
                "Files are never uploaded to an intermediary server. The sharing computer "
                "must be reachable at the configured IP and TCP port."
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
        self.share_peer_key = Gtk.Entry()
        self.share_peer_key.set_placeholder_text("Peer’s ssh-ed25519 public key")
        grid = Gtk.Grid(column_spacing=12, row_spacing=9)
        self._row(grid, 0, "Saved share", self.share_choice)
        self._row(grid, 1, "Display name", self.share_name)
        self._row(grid, 2, "Local folder", self.share_folder)
        self._row(grid, 3, "Address peers use", self.share_host)
        self._row(grid, 4, "TCP port", self.share_port)
        self._row(grid, 5, "Allowed peer public key", self.share_peer_key)
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
        delete = Gtk.Button(label="Delete")
        delete.connect("clicked", self._delete_share)
        for button in (save, stop, invitation, delete):
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
        grid = Gtk.Grid(column_spacing=12, row_spacing=9)
        self._row(grid, 0, "Saved connection", self.connection_choice)
        self._row(grid, 1, "Display name", self.connection_name)
        self._row(grid, 2, "Peer IP / DNS", self.connection_host)
        self._row(grid, 3, "Peer TCP port", self.connection_port)
        self._row(grid, 4, "Peer host public key", self.connection_host_key)
        self._row(grid, 5, "My local folder", self.connection_folder)
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
        connect = Gtk.Button(label="Save and connect")
        connect.connect("clicked", self._save_connection)
        delete = Gtk.Button(label="Remove connection")
        delete.connect("clicked", self._delete_connection)
        for button in (load, connect, delete):
            buttons.pack_start(button, False, False, 0)
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
        self.share_peer_key.set_text(share.allowed_peer_key if share else "")
        if share and Path(share.local_path).is_dir():
            self.share_folder.set_filename(str(Path(share.local_path).expanduser()))

    def _save_share(self, _button: Gtk.Button) -> None:
        try:
            folder = self.share_folder.get_filename()
            if not folder:
                raise PeerError("Select the local folder to share")
            share = self._selected_share()
            name = self.share_name.get_text().strip() or "Peer shared folder"
            advertised_host = validate_host(self.share_host.get_text())
            port = validate_port(self.share_port.get_value_as_int())
            allowed_peer_key = normalize_public_key(self.share_peer_key.get_text())
            if share is None:
                share = PeerShare("", folder, "")
                self.controller.config.peer_shares.append(share)
            else:
                self.controller.peers.stop(share.id)
            share.name = name
            share.local_path = folder
            share.advertised_host = advertised_host
            share.port = port
            share.allowed_peer_key = allowed_peer_key
            share.enabled = True
            self.controller.peers.start(share)
            share.last_status = f"Listening on TCP {share.port}"
            self.controller.save()
            self._reload_share_choices(share.id)
            self._set_status("Direct encrypted share is running.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

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
            value = self.controller.peers.invitation(share)
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(value, -1)
            self._set_status("Invitation copied. Send it through a trusted channel.", False)
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

    def _load_invitation(self, _button: Gtk.Button) -> None:
        buffer = self.invitation_text.get_buffer()
        value = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        try:
            invitation = PeerInvitation.decode(value)
            self.connection_name.set_text(invitation.name)
            self.connection_host.set_text(invitation.host)
            self.connection_port.set_value(invitation.port)
            self.connection_host_key.set_text(invitation.host_key)
            self._set_status("Invitation loaded. Select your local folder and connect.", False)
        except Exception as exc:
            self._set_status(str(exc), True)

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
            )
            account = self._selected_connection()
            remote = account.remote if account else "peer-" + datetime.now().strftime("%H%M%S")
            candidate = remote + "-verify"
            try:
                self.controller.rclone.delete_remote(candidate)
            except Exception:
                pass
            self.controller.peers.configure_connection(candidate, invitation)
            try:
                self.controller.rclone.validate_remote(candidate)
            finally:
                try:
                    self.controller.rclone.delete_remote(candidate)
                except Exception:
                    pass
            self.controller.peers.configure_connection(remote, invitation)
            if account is None:
                account = Account(remote, Provider.PEER, invitation.name)
                self.controller.config.accounts.append(account)
                job = SyncJob(
                    account_remote=remote,
                    local_path=folder,
                    name=invitation.name,
                    cloud_location_name="Direct encrypted peer",
                    mode=SyncMode.TWO_WAY,
                )
                self.controller.config.jobs.append(job)
            else:
                job = next((item for item in self.controller.config.jobs if item.account_remote == remote), None)
                if job:
                    job.local_path = folder
                    job.name = invitation.name
                    job.initialized = False
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
            self._set_status("Peer verified and synchronization started.", False)
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
                account_state, account_icon = "Synchronizing", "tuxdrive-sync"
            elif any(job.last_error for job in account_jobs):
                account_state, account_icon = "Needs attention", "tuxdrive-error"
            else:
                account_state = "Connected"
                account_icon = account.provider.icon_name
            icon = Gtk.Image.new_from_icon_name(account_icon, Gtk.IconSize.DND)
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
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_border_width(14)
        top = Gtk.Box(spacing=12)
        if job.id in self.controller.engine.running_jobs:
            icon_name = "tuxdrive-sync"
        elif job.last_error:
            icon_name = "tuxdrive-error"
        elif not job.enabled:
            icon_name = "media-playback-pause-symbolic"
        elif job.initialized or mounted:
            icon_name = "tuxdrive"
        else:
            icon_name = "folder-remote-symbolic"
        top.pack_start(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DND), False, False, 0)
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
        remove = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        remove.set_tooltip_text("Remove synchronization")
        remove.connect("clicked", self._remove_job, job)
        for widget in (sync, cancel, open_button, share_button, rename_button, edit_button, log_button):
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
        providers = [provider for provider in Provider if provider is not Provider.PEER]
        for index, provider in enumerate(providers, start=1):
            button = Gtk.Button(label=provider.label)
            button.set_image(Gtk.Image.new_from_icon_name(provider.icon_name, Gtk.IconSize.DND))
            button.set_always_show_image(True)
            button.set_hexpand(True)
            button.connect("clicked", lambda _button, response=index: dialog.response(response))
            grid.attach(button, (index - 1) % 2, (index - 1) // 2, 1, 1)
        area.pack_start(grid, True, True, 8)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.show_all()
        response = dialog.run()
        dialog.destroy()
        if 1 <= response <= len(providers):
            provider = providers[response - 1]
            OAuthWizard(self, self.controller.rclone, provider, self.controller.add_account)

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
        else:
            self.message("This Nextcloud account uses its configured server URL.")

    def _reconnect(self, _item: Gtk.MenuItem, account: Account) -> None:
        if account.provider is Provider.PEER:
            self._show_peer_sharing(_item)
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
        for widget in (launch, notifications, minimized):
            dialog.get_content_area().pack_start(widget, False, False, 6)
        dialog.add_button("Peer-to-peer sharing…", 3)
        dialog.add_button("Check for updates", 2)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.controller.config.settings.launch_at_login = launch.get_active()
            self.controller.config.settings.notifications = notifications.get_active()
            self.controller.config.settings.start_minimized = minimized.get_active()
            self.controller.save()
            self.controller.configure_autostart()
        dialog.destroy()
        if response == 2:
            self._check_for_updates()
        elif response == 3:
            self._show_peer_sharing(_button)

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
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _hide_instead_of_close(self, *_args) -> bool:
        self.hide()
        self.controller.notify("TuxDrive is still running", "Synchronization continues in the background.")
        return True


class TuxDriveApplication(Gtk.Application):
    def __init__(self, background: bool = False) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.updater = UpdateManager(__version__)
        self.background = background
        self.store = ConfigStore()
        try:
            self.config = self.store.load()
        except RuntimeError:
            self.config = AppConfig()
        self.rclone = RcloneClient(self.config.settings.rclone_path)
        self.engine = SyncEngine(self.config.settings.rclone_path)
        self.peers = PeerManager(self.config.settings.rclone_path)
        self.window: MainWindow | None = None
        self.indicator = None
        self._runtime_ready_once = False
        self._last_started: dict[str, datetime] = {}
        self._mount_failures: dict[str, list[datetime]] = {}

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.hold()
        LOGGER.info("GTK application startup completed")
        self._install_css()
        GLib.timeout_add_seconds(30, self._scheduler_tick)
        self.configure_autostart()
        self._create_indicator()

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

    def add_account(self, account: Account) -> None:
        self.config.accounts = [item for item in self.config.accounts if item.remote != account.remote]
        self.config.accounts.append(account)
        self.save()
        if self.window:
            self.window.refresh()
            self.window.message(f"{account.display_name} connected successfully.")

    def run_job(self, job: SyncJob, quiet: bool = False) -> None:
        self.engine.configure_jobs(self.config.jobs)
        if not job.enabled and not quiet:
            job.enabled = True
        if job.id in self.engine.running_jobs:
            if self.window and not quiet:
                self.window.message(f"{job.name} is already synchronizing.")
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
        self._set_tray_state("syncing", job.name)
        self._last_started[job.id] = datetime.now(timezone.utc)
        if self.window:
            self.window.refresh()
        started = self.engine.run_async(job, self._job_finished)
        if not started and self.window and not quiet:
            self.window.message("The job could not be started.", Gtk.MessageType.WARNING)

    def stop_job(self, job: SyncJob) -> None:
        self.engine.stop_callbacks(job.id)
        stopped = self.engine.stop_mount(job) if job.mode is SyncMode.VIRTUAL_DRIVE else self.engine.cancel(job.id)
        if stopped:
            job.last_status = "Stopped"
            self.save()
            if self.window:
                self.window.refresh()

    def _job_finished(self, result: JobResult) -> None:
        GLib.idle_add(self._apply_job_result, result)

    def _apply_job_result(self, result: JobResult) -> bool:
        job = next((item for item in self.config.jobs if item.id == result.job_id), None)
        if not job:
            return False
        now = datetime.now(timezone.utc)
        job.last_run = now.isoformat()
        job.last_status = result.message
        job.last_error = "" if result.success else result.message
        if result.requires_resync:
            job.initialized = False
            job.enabled = False
            job.last_status = f"{result.message} Automatic sync paused; recovery sync required."
            job.last_error = job.last_status
        if result.success and job.mode is not SyncMode.VIRTUAL_DRIVE:
            job.initialized = True
        self._set_tray_state("ready" if result.success else "error", result.message)
        LOGGER.info("Job %s finished: success=%s message=%s", job.id, result.success, result.message)
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

    def notify(self, title: str, body: str) -> None:
        if not self.config.settings.notifications:
            return
        notification = Gio.Notification.new(title)
        notification.set_body(body)
        self.send_notification(None, notification)

    def configure_autostart(self) -> None:
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
            self.save()
            for job in self.config.jobs:
                if job.enabled and job.mode is SyncMode.VIRTUAL_DRIVE:
                    self.run_job(job, quiet=True)
                elif job.enabled and job.initialized and job.realtime_sync:
                    self.start_callbacks(job)
        return False

    @staticmethod
    def _install_css() -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b".sidebar { background: @theme_base_color; border-right: 1px solid alpha(@theme_fg_color, .12); }"
            b"list row { border-bottom: 1px solid alpha(@theme_fg_color, .10); }"
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
