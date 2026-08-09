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

    def test_all_provider_icons_are_packaged(self):
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        for provider in ("dropbox", "box", "pcloud", "mega", "proton-drive", "nextcloud"):
            self.assertTrue(Path(f"packaging/tuxdrive-{provider}.svg").exists())
        self.assertIn("dropbox box pcloud mega proton-drive nextcloud", build_script)


if __name__ == "__main__":
    unittest.main()
