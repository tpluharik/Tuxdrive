import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class PackagingTests(unittest.TestCase):
    def test_launcher_points_to_parent_of_installed_package(self):
        launcher = Path("packaging/tuxdrive-launcher").read_text(encoding="utf-8")
        self.assertIn("unset PYTHONPATH PYTHONHOME", launcher)
        self.assertIn("/usr/bin/python3 -I", launcher)
        self.assertIn('sys.path.insert(0,"/usr/lib")', launcher)
        self.assertIn('run_module("tuxdrive.app"', launcher)
        self.assertIn('--system-check', launcher)
        self.assertIn('tuxdrive-doctor', launcher)
        self.assertIn('run_module("tuxdrive.platform_support"', launcher)

    def test_upgrade_stops_only_the_exact_old_tuxdrive_application(self):
        postinst = Path("packaging/DEBIAN/postinst").read_text(encoding="utf-8")
        self.assertIn('if [ "${1:-}" = "configure" ] && [ -n "${2:-}" ]', postinst)
        self.assertIn('runpy.run_module("tuxdrive.app",run_name="__main__")', postinst)
        self.assertIn('kill -INT "$tuxdrive_pid"', postinst)
        self.assertIn('kill -TERM "$tuxdrive_pid"', postinst)

    def test_build_has_installed_layout_import_smoke_test(self):
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn('PYTHONPATH="$PACKAGE_ROOT/usr/lib"', build_script)
        self.assertIn('find_spec("tuxdrive.app")', build_script)

    def test_gtk3_and_gdk3_are_pinned_before_repository_import(self):
        app = Path("src/tuxdrive/app.py").read_text(encoding="utf-8")
        gdk_requirement = 'gi.require_version("Gdk", "3.0")'
        gtk_requirement = 'gi.require_version("Gtk", "3.0")'
        repository_import = "from gi.repository import Gtk, Gdk, Gio, GLib"
        self.assertIn(gdk_requirement, app)
        self.assertIn(gtk_requirement, app)
        self.assertIn(repository_import, app)
        self.assertLess(app.index(gdk_requirement), app.index(repository_import))
        self.assertLess(app.index(gtk_requirement), app.index(repository_import))

    def test_visual_folder_tree_live_log_and_activity_icons_are_present(self):
        app = Path("src/tuxdrive/app.py").read_text(encoding="utf-8")
        self.assertIn("class CloudFolderTree", app)
        self.assertIn("Gtk.TreeStore(bool, str, str, bool)", app)
        self.assertIn('Gtk.Expander(label=tr("live_log"))', app)
        self.assertIn('account.provider.icon_name', app)
        self.assertIn('toggle.set_name("tuxdrive-job-switch")', app)
        self.assertIn('switch#tuxdrive-job-switch', app)
        self.assertIn("class ExceptionRulesEditor", app)
        self.assertIn('"Exclude file and retry"', app)
        self.assertIn('"Allow unsafe download and retry"', app)
        self.assertIn('label=tr("rename")', app)
        self.assertIn("Gtk.ProgressBar()", app)
        self.assertIn('"Downloading… {fraction:.0%}"', app)
        self.assertIn("Verifying cloud access…", app)
        self.assertIn("Reconnect / refresh credentials", app)
        self.assertIn("class PeerSharingDialog", app)
        self.assertIn("Proton Drive two-factor authentication", app)
        self.assertIn("Save and connect", app)
        self.assertIn("class ProfileDialog", app)
        self.assertIn("TuxDrive Profile / migrate", app)
        self.assertIn("class CollaborativeEditorDialog", app)
        self.assertIn('Gtk.Label(label="Collaborate")', app)
        self.assertIn("class HelpCenterDialog", app)
        self.assertIn('language.flag', app)
        self.assertIn('JOB_DND_MIME = "application/x-tuxdrive-synchronized-folder"', app)
        self.assertIn("Gtk.TargetEntry.new(JOB_DND_MIME, Gtk.TargetFlags.SAME_APP, 0)", app)
        self.assertIn("drag_source_set(", app)
        self.assertIn("drag_dest_set(", app)
        self.assertIn('tr("minimize_group")', app)
        self.assertIn('tr("expand_group")', app)
        self.assertIn("if group.collapsed:", app)
        self.assertIn("account.provider.icon_name", app)

    def test_peer_runtime_and_key_generator_are_installed(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("openssh-client", control)
        self.assertIn("qrencode", control)
        self.assertIn("zbar-tools", control)
        self.assertIn('find_spec("tuxdrive.peer")', build_script)
        self.assertIn('docs/TESTING.md', build_script)
        self.assertIn('docs/ROADMAP.md', build_script)
        self.assertIn("python3-cryptography", control)
        self.assertIn("python3-defusedxml", control)
        self.assertIn("libsecret-tools", control)
        self.assertIn("tuxdrive-rclone-password", build_script)
        self.assertIn('find_spec("tuxdrive.migration")', build_script)
        self.assertIn("tuxdrive-update-helper", build_script)
        self.assertIn('find_spec("tuxdrive.update_helper")', build_script)
        self.assertIn('find_spec("tuxdrive.github_sync")', build_script)

    def test_all_provider_icons_are_packaged(self):
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        for provider in ("dropbox", "box", "pcloud", "mega", "proton-drive", "nextcloud", "github"):
            self.assertTrue(Path(f"packaging/tuxdrive-{provider}.svg").exists())
        self.assertIn("dropbox box pcloud mega proton-drive nextcloud github", build_script)
        self.assertIn("git", Path("packaging/DEBIAN/control").read_text(encoding="utf-8"))

    def test_nautilus_extension_is_packaged_with_safe_app_actions(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        extension = Path("packaging/nautilus-extension-tuxdrive.py").read_text(encoding="utf-8")
        app = Path("src/tuxdrive/app.py").read_text(encoding="utf-8")
        self.assertIn("Recommends: python3-nautilus", control)
        self.assertIn("usr/share/nautilus-python/extensions", build_script)
        self.assertNotIn('gi.require_version("Nautilus"', extension)
        self.assertIn('group.activate_action(action, parameter)', extension)
        self.assertIn('"open-online-path"', extension)
        self.assertIn("nautilus-state.json", extension)
        self.assertIn('get("nautilus_integration", True)', extension)
        self.assertIn('"--offline-path"', extension)
        self.assertIn('"--online-only-path"', extension)
        self.assertNotIn("resolve(strict=False)", extension)
        self.assertIn('(\"sync-path\", self._nautilus_sync_path)', app)
        self.assertIn('(\"open-online-path\", self._nautilus_open_online)', app)
        self.assertIn('(\"offline-path\", self._nautilus_keep_offline)', app)
        self.assertIn('(\"online-only-path\", self._nautilus_make_online_only)', app)
        self.assertIn('_desktop_open_command(url)', app)
        self.assertIn("Gio.ApplicationFlags.HANDLES_COMMAND_LINE", app)
        self.assertIn('if action == "open-online-path"', extension)
        self.assertIn("def do_command_line", app)
        self.assertIn("command_line_path(arguments, name)", app)
        self.assertIn("_request_offline_path", app)
        self.assertIn('name.startswith(("config-", "nautilus-state-"))', extension)
        self.assertNotIn("self.activate()\n        if not self._runtime_ready_once:\n            self._pending_nautilus_online", app)
        self.assertIn("_publish_nautilus_state", app)
        self.assertIn("_pending_nautilus_paths", app)
        self.assertIn('"configured_offline_paths"', app)
        self.assertIn('"online_only_paths"', app)
        self.assertIn('"__tuxdrive__"', extension)
        self.assertIn("Prefer the small extension snapshot", extension)
        self.assertIn("_LAST_VALID_JOBS", extension)
        self.assertIn("len(paths) == 1", extension)
        self.assertIn('relative == rule or relative.startswith(rule.rstrip("/") + "/")', extension)
        self.assertNotIn("from tuxdrive", extension)
        self.assertIn("without remounting", app)
        self.assertNotIn("policy_result = self.engine.restart_mount", app)
        self.assertIn("Reconnects must never trigger an implicit download", app)
        self.assertIn("Do not mount the cloud merely to make it online-only", app)
        self.assertIn("dispatch that exact", app)
        self.assertIn("verified_offline_rules(job)", app)
        self.assertNotIn("for relative in list(job.offline_paths)", app)

    def test_nautilus_info_provider_completes_and_packages_emblems(self):
        extension = Path("packaging/nautilus-extension-tuxdrive.py").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("def update_file_info_full", extension)
        self.assertIn("Nautilus.OperationResult.COMPLETE", extension)
        for state in ("synced", "syncing", "streaming", "paused", "pending", "error"):
            self.assertTrue(Path(f"packaging/emblem-tuxdrive-{state}.svg").exists())
        self.assertIn("scalable/emblems", build_script)

    def test_nautilus_emblems_are_unbranded_and_visually_distinct(self):
        palette = {
            "synced": "#15803D",
            "syncing": "#1565C0",
            "streaming": "#00838F",
            "paused": "#6D28D9",
            "pending": "#D97706",
            "error": "#C62828",
        }
        descriptions: set[str] = set()
        for state, color in palette.items():
            path = Path(f"packaging/emblem-tuxdrive-{state}.svg")
            source = path.read_text(encoding="utf-8")
            root = ET.fromstring(source)
            self.assertEqual(root.attrib.get("data-state"), state)
            self.assertIn(color, source)
            self.assertNotIn("#20252b", source.lower())
            self.assertNotIn("#f4a51c", source.lower())
            description = root.find("{http://www.w3.org/2000/svg}desc")
            self.assertIsNotNone(description)
            descriptions.add(description.text or "")
        self.assertEqual(len(set(palette.values())), len(palette))
        self.assertEqual(len(descriptions), len(palette))

    def test_optional_integrations_do_not_block_core_install(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        depends, recommends = control.split("Depends: ", 1)[1].split("\n", 1)[0], control.split("Recommends: ", 1)[1].split("\n", 1)[0]
        for package in ("python3-nautilus", "fuse3", "tor", "obfs4proxy", "natpmpc"):
            self.assertNotIn(package, depends)
            self.assertIn(package, recommends)
        self.assertIn("install-capabilities.json", Path("packaging/DEBIAN/postinst").read_text(encoding="utf-8"))

    def test_release_workflow_builds_debian_only(self):
        workflow = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
        self.assertIn("Build Debian package", workflow)
        self.assertNotIn("macos-experimental-package", workflow)
        self.assertFalse(Path("scripts/build-macos-pkg.sh").exists())


if __name__ == "__main__":
    unittest.main()
