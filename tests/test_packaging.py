import unittest
from pathlib import Path


class PackagingTests(unittest.TestCase):
    def test_launcher_points_to_parent_of_installed_package(self):
        launcher = Path("packaging/tuxdrive-launcher").read_text(encoding="utf-8")
        self.assertIn('PYTHONPATH="/usr/lib', launcher)
        self.assertNotIn('PYTHONPATH="/usr/lib/tuxdrive', launcher)
        self.assertIn("-m tuxdrive.app", launcher)

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
        self.assertIn('Gtk.Expander(label="Live activity log")', app)
        self.assertIn('icon_name = "tuxdrive-sync"', app)
        self.assertIn('icon_name = "tuxdrive-error"', app)
        self.assertIn("class ExceptionRulesEditor", app)
        self.assertIn('"Exclude file and retry"', app)
        self.assertIn('"Allow unsafe download and retry"', app)
        self.assertIn('label="Rename"', app)
        self.assertIn("Gtk.ProgressBar()", app)
        self.assertIn('"Downloading… {fraction:.0%}"', app)
        self.assertIn("Verifying cloud access…", app)
        self.assertIn("Reconnect / refresh credentials", app)
        self.assertIn("class PeerSharingDialog", app)
        self.assertIn("Proton Drive two-factor authentication", app)
        self.assertIn("Save and connect", app)

    def test_peer_runtime_and_key_generator_are_installed(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("openssh-client", control)
        self.assertIn("qrencode", control)
        self.assertIn("zbar-tools", control)
        self.assertIn('find_spec("tuxdrive.peer")', build_script)
        self.assertIn('docs/TESTING.md', build_script)
        self.assertIn('docs/ROADMAP.md', build_script)

    def test_all_provider_icons_are_packaged(self):
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        for provider in ("dropbox", "box", "pcloud", "mega", "proton-drive", "nextcloud"):
            self.assertTrue(Path(f"packaging/tuxdrive-{provider}.svg").exists())
        self.assertIn("dropbox box pcloud mega proton-drive nextcloud", build_script)

    def test_nautilus_extension_is_packaged_with_safe_app_actions(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        extension = Path("packaging/nautilus-extension-tuxdrive.py").read_text(encoding="utf-8")
        app = Path("src/tuxdrive/app.py").read_text(encoding="utf-8")
        self.assertIn("python3-nautilus", control)
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
        self.assertIn('["xdg-open", url]', app)
        self.assertIn("Gio.ApplicationFlags.HANDLES_COMMAND_LINE", app)
        self.assertIn('"open-online-path": "--open-online"', extension)
        self.assertIn("def do_command_line", app)
        self.assertNotIn("self.activate()\n        if not self._runtime_ready_once:\n            self._pending_nautilus_online", app)
        self.assertIn("_publish_nautilus_state", app)
        self.assertIn("_pending_nautilus_paths", app)

    def test_nautilus_info_provider_completes_and_packages_emblems(self):
        extension = Path("packaging/nautilus-extension-tuxdrive.py").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("def update_file_info_full", extension)
        self.assertIn("Nautilus.OperationResult.COMPLETE", extension)
        for state in ("synced", "syncing", "streaming", "paused", "pending", "error"):
            self.assertTrue(Path(f"packaging/emblem-tuxdrive-{state}.svg").exists())
        self.assertIn("scalable/emblems", build_script)


if __name__ == "__main__":
    unittest.main()
