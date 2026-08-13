import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class PackagingTests(unittest.TestCase):
    def test_launcher_points_to_parent_of_installed_package(self):
        launcher = Path("packaging/tuxindrive-launcher").read_text(encoding="utf-8")
        self.assertIn("unset PYTHONPATH PYTHONHOME", launcher)
        self.assertIn("/usr/bin/python3 -I", launcher)
        self.assertIn('sys.path.insert(0,"/usr/lib")', launcher)
        self.assertIn('run_module("tuxindrive.app"', launcher)
        self.assertIn('--system-check', launcher)
        self.assertIn('tuxindrive-doctor', launcher)
        self.assertIn('run_module("tuxindrive.platform_support"', launcher)
        self.assertIn('"tuxdrive-doctor"', launcher)
        self.assertIn('.tuxdrive-encrypted', launcher)

    def test_upgrade_stops_only_the_exact_old_tuxindrive_application(self):
        postinst = Path("packaging/DEBIAN/postinst").read_text(encoding="utf-8")
        self.assertIn('if [ "${1:-}" = "configure" ] && [ -n "${2:-}" ]', postinst)
        self.assertIn('runpy.run_module("tuxindrive.app",run_name="__main__")', postinst)
        self.assertIn('runpy.run_module("tuxdrive.app",run_name="__main__")', postinst)
        self.assertIn('kill -INT "$tuxindrive_pid"', postinst)
        self.assertIn('kill -TERM "$tuxindrive_pid"', postinst)

    def test_build_has_installed_layout_import_smoke_test(self):
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn('PYTHONPATH="$PACKAGE_ROOT/usr/lib"', build_script)
        self.assertIn('find_spec("tuxindrive.app")', build_script)
        self.assertIn('usr/bin/tuxdrive', build_script)
        self.assertIn('tuxdrive.service', build_script)
        self.assertIn('LEGACY_OUTPUT=', build_script)

    def test_debian_identity_is_an_explicit_signed_updater_compatibility_abi(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        self.assertIn("Package: tuxdrive", control)
        from tuxindrive import __version__
        self.assertIn(f"Version: {__version__}", control)
        self.assertIn(f"Provides: tuxindrive (= {__version__})", control)
        helper = Path("packaging/tuxindrive-rclone-password").read_text(encoding="utf-8")
        self.assertIn("lookup application tuxdrive purpose rclone-config", helper)

    def test_gtk3_and_gdk3_are_pinned_before_repository_import(self):
        app = Path("src/tuxindrive/app.py").read_text(encoding="utf-8")
        gdk_requirement = 'gi.require_version("Gdk", "3.0")'
        gtk_requirement = 'gi.require_version("Gtk", "3.0")'
        repository_import = "from gi.repository import Gtk, Gdk, Gio, GLib"
        self.assertIn(gdk_requirement, app)
        self.assertIn(gtk_requirement, app)
        self.assertIn(repository_import, app)
        self.assertLess(app.index(gdk_requirement), app.index(repository_import))
        self.assertLess(app.index(gtk_requirement), app.index(repository_import))

    def test_visual_folder_tree_live_log_and_activity_icons_are_present(self):
        app = Path("src/tuxindrive/app.py").read_text(encoding="utf-8")
        self.assertIn("class CloudFolderTree", app)
        self.assertIn("Gtk.TreeStore(bool, str, str, bool)", app)
        self.assertIn('Gtk.Expander(label=tr("live_log"))', app)
        self.assertIn('tr("download_now")', app)
        self.assertIn("NetworkUsageMeter()", app)
        self.assertIn('account.provider.icon_name', app)
        self.assertIn('toggle.set_name("tuxindrive-job-switch")', app)
        themes = Path("src/tuxindrive/themes.py").read_text(encoding="utf-8")
        self.assertIn('switch#tuxindrive-job-switch', themes)
        self.assertIn("class ExceptionRulesEditor", app)
        self.assertIn('"Exclude file and retry"', app)
        self.assertIn('"Allow unsafe download and retry"', app)
        self.assertIn('label=tr("rename")', app)
        self.assertIn("Gtk.ProgressBar()", app)
        self.assertIn('"Downloading… {fraction:.0%}"', app)
        self.assertIn("Verifying cloud access…", app)
        self.assertIn("Reconnect / refresh credentials", app)
        self.assertIn("class PeerSharingDialog", app)
        self.assertIn("class ProtonAuthDialog", app)
        self.assertIn("Linux Secret Service", app)
        self.assertIn("Install CLI and connect", app)
        self.assertIn("download/drive/cli/index.html", app)
        self.assertIn("Save and connect", app)
        self.assertIn("class ProfileDialog", app)
        self.assertIn("TuxInDrive Profile / migrate", app)
        self.assertIn("class CollaborativeEditorDialog", app)
        self.assertIn('Gtk.Label(label="Collaborate")', app)
        self.assertIn("class HelpCenterDialog", app)
        self.assertIn('language.flag', app)
        self.assertIn('JOB_DND_TARGET = "UTF8_STRING"', app)
        self.assertIn("Gtk.TargetEntry.new(JOB_DND_TARGET, Gtk.TargetFlags.SAME_APP, 0)", app)
        self.assertIn("drag_source_set(", app)
        self.assertIn('drag_source_set_icon_name("open-menu-symbolic")', app)
        self.assertIn("drag_dest_set(", app)
        self.assertIn("job_drag_payload(job_id)", app)
        self.assertIn("job_id_from_drag_payload(selection.get_text())", app)
        self.assertIn('tr("minimize_group")', app)
        self.assertIn('tr("expand_group")', app)
        self.assertIn("if group.collapsed:", app)
        self.assertIn("account.provider.icon_name", app)
        self.assertIn('theme.append(visual_theme.key, visual_theme.label)', app)
        self.assertIn('self.controller.apply_visual_theme(selected_theme)', app)
        self.assertIn('get_style_context().add_class("job-card")', app)
        self.assertIn('get_style_context().add_class("account-card")', app)
        self.assertIn('get_style_context().add_class("activity-panel")', app)
        self.assertIn('normalize_theme(key) == "bento_cloud"', app)
        for design in ("nordic_glass", "bento_cloud", "midnight_sync"):
            self.assertIn(f'"{design}"', themes)

    def test_peer_runtime_and_key_generator_are_installed(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("openssh-client", control)
        self.assertIn("qrencode", control)
        self.assertIn("zbar-tools", control)
        self.assertIn('find_spec("tuxindrive.peer")', build_script)
        self.assertIn('docs/TESTING.md', build_script)
        self.assertIn('docs/ROADMAP.md', build_script)
        self.assertIn("python3-cryptography", control)
        self.assertIn("python3-defusedxml", control)
        self.assertIn("libsecret-tools", control)
        self.assertIn("tuxindrive-rclone-password", build_script)
        self.assertIn('find_spec("tuxindrive.migration")', build_script)
        self.assertIn("tuxindrive-update-helper", build_script)
        self.assertIn('find_spec("tuxindrive.update_helper")', build_script)
        self.assertIn('find_spec("tuxindrive.github_sync")', build_script)
        self.assertIn('find_spec("tuxindrive.proton")', build_script)

    def test_all_provider_icons_are_packaged(self):
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        for provider in ("dropbox", "box", "pcloud", "mega", "proton-drive", "nextcloud", "github"):
            self.assertTrue(Path(f"packaging/tuxindrive-{provider}.svg").exists())
        self.assertIn("dropbox box pcloud mega proton-drive nextcloud github", build_script)
        self.assertIn("git", Path("packaging/DEBIAN/control").read_text(encoding="utf-8"))

    def test_nautilus_extension_is_packaged_with_safe_app_actions(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        extension = Path("packaging/nautilus-extension-tuxindrive.py").read_text(encoding="utf-8")
        app = Path("src/tuxindrive/app.py").read_text(encoding="utf-8")
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
        self.assertIn('"__tuxindrive__"', extension)
        self.assertIn("Prefer the small extension snapshot", extension)
        self.assertIn("_LAST_VALID_JOBS", extension)
        self.assertIn("len(paths) == 1", extension)
        self.assertIn('relative == rule or relative.startswith(rule.rstrip("/") + "/")', extension)
        self.assertNotIn("from tuxindrive", extension)
        self.assertIn("without remounting", app)
        self.assertNotIn("policy_result = self.engine.restart_mount", app)
        self.assertIn("Reconnects must never trigger an implicit download", app)
        self.assertIn("Do not mount the cloud merely to make it online-only", app)
        self.assertIn("dispatch that exact", app)
        self.assertIn("verified_offline_rules(job)", app)
        self.assertNotIn("for relative in list(job.offline_paths)", app)

    def test_nautilus_info_provider_completes_and_packages_emblems(self):
        extension = Path("packaging/nautilus-extension-tuxindrive.py").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("def update_file_info_full", extension)
        self.assertIn("Nautilus.OperationResult.COMPLETE", extension)
        for state in ("synced", "syncing", "streaming", "paused", "pending", "error"):
            self.assertTrue(Path(f"packaging/emblem-tuxindrive-{state}.svg").exists())
            self.assertIn(f'emblem-tuxdrive-${{STATE}}.svg', build_script)
        self.assertIn('file_info.add_emblem(emblem)', extension)
        self.assertIn('f"emblem-tuxindrive-{state}"', extension)
        self.assertIn("scalable/emblems", build_script)

    def test_job_action_opens_online_folder_without_creating_share_link(self):
        app = Path("src/tuxindrive/app.py").read_text(encoding="utf-8")
        i18n = Path("src/tuxindrive/i18n.py").read_text(encoding="utf-8")
        self.assertIn('Gtk.Button(label=tr("open_online_folder"))', app)
        self.assertIn('self.controller._open_online_path(str(job.local))', app)
        self.assertNotIn('Gtk.Button(label=tr("share_link"))', app)
        self.assertNotIn("def _share_job", app)
        self.assertNotIn("Creating a provider share link", app)
        self.assertIn('account.provider is Provider.PROTON_DRIVE and account.backend == "proton_cli"', app)
        self.assertIn("does not\n            # currently publish a stable private web-route contract", app)
        self.assertNotIn('"share_link":', i18n)
        self.assertEqual(i18n.count('"open_online_folder":'), 6)

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
            path = Path(f"packaging/emblem-tuxindrive-{state}.svg")
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

    def test_release_workflows_cover_all_packaged_platforms(self):
        workflow = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
        self.assertIn("Build Debian package", workflow)
        platforms = Path(".github/workflows/platform-packages.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: windows-latest", platforms)
        self.assertIn("runs-on: macos-14", platforms)
        self.assertIn("name: tuxindrive-android", platforms)
        self.assertTrue(Path("scripts/build-windows.ps1").is_file())
        self.assertTrue(Path("scripts/build-macos.sh").is_file())
        self.assertTrue(Path("packaging/windows/TuxInDrive.iss").is_file())
        self.assertTrue(Path("android/app/src/main/AndroidManifest.xml").is_file())
        self.assertTrue(Path("android/app/src/main/java/io/github/tuxindrive/mobile/NetworkUsageMeter.kt").is_file())

    def test_native_build_paths_match_ci_runner_layout(self):
        platforms = Path(".github/workflows/platform-packages.yml").read_text(encoding="utf-8")
        windows = Path("scripts/build-windows.ps1").read_text(encoding="utf-8")
        macos = Path("scripts/build-macos.sh").read_text(encoding="utf-8")
        self.assertIn("mingw-w64-ucrt-x86_64-pyinstaller", platforms)
        self.assertNotIn("mingw-w64-ucrt-x86_64-python-pyinstaller", platforms)
        self.assertIn("mkdir -p android/app/libs", platforms)
        self.assertIn("test -s \"${GITHUB_WORKSPACE}/android/app/libs/rclone.aar\"", platforms)
        self.assertNotIn("cygpath", windows)
        self.assertIn('if ($LASTEXITCODE -ne 0)', windows)
        self.assertIn("PackageOnly", windows)
        self.assertIn("VERSION=$(sed", Path("scripts/build-deb.sh").read_text(encoding="utf-8"))
        windows_msys2 = Path("scripts/build-windows-msys2.sh").read_text(encoding="utf-8")
        self.assertIn('--specpath build', windows_msys2)
        self.assertIn('--add-data "../branding/tuxindrive-logo.png:branding"', windows_msys2)
        self.assertTrue((Path("build") / "../branding/tuxindrive-logo.png").resolve().is_file())
        self.assertNotIn('$project_root/branding/tuxindrive-logo.png', windows_msys2)
        self.assertIn("test -s build/windows/TuxInDrive/TuxInDrive.exe", windows_msys2)
        self.assertIn("run: sh scripts/build-windows-msys2.sh", platforms)
        self.assertIn("run: scripts/build-windows.ps1 -PackageOnly", platforms)
        self.assertIn('$project_root/branding/tuxindrive-logo.png', macos)
        android_build = Path("android/app/build.gradle.kts").read_text(encoding="utf-8")
        self.assertIn("sourceCompatibility = JavaVersion.VERSION_17", android_build)
        self.assertIn("targetCompatibility = JavaVersion.VERSION_17", android_build)
        self.assertIn("jvmToolchain(17)", android_build)
        android_ui = Path("android/app/src/main/java/io/github/tuxindrive/mobile/MainActivity.kt").read_text(encoding="utf-8")
        self.assertIn("NetworkMeter(networkUsage)", android_ui)
        self.assertIn("downloadedToday", android_ui)


if __name__ == "__main__":
    unittest.main()
