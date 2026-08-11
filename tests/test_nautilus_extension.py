import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def load_extension():
    class FakeMenu:
        def __init__(self):
            self.items = []

        def append_item(self, item):
            self.items.append(item)

    class FakeMenuItem:
        def __init__(self, **values):
            self.values = values
            self.submenu = None
            self.sensitive = True

        def connect(self, *_args):
            return None

        def set_submenu(self, submenu):
            self.submenu = submenu

        def set_sensitive(self, value):
            self.sensitive = value

    gi = types.ModuleType("gi")
    repository = types.ModuleType("gi.repository")
    repository.Gio = types.SimpleNamespace()
    repository.GLib = types.SimpleNamespace()
    repository.GObject = types.SimpleNamespace(GObject=type("GObject", (), {}))
    repository.Nautilus = types.SimpleNamespace(
        MenuProvider=type("MenuProvider", (), {}),
        InfoProvider=type("InfoProvider", (), {}),
        FileInfo=object,
        Menu=FakeMenu,
        MenuItem=FakeMenuItem,
        OperationResult=types.SimpleNamespace(COMPLETE=0),
    )
    gi.repository = repository
    spec = importlib.util.spec_from_file_location(
        "tuxdrive_nautilus_extension_test",
        Path("packaging/nautilus-extension-tuxdrive.py"),
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class NautilusExtensionTests(unittest.TestCase):
    def test_file_rule_does_not_tag_siblings_or_parent(self):
        extension = load_extension()
        self.assertTrue(extension._matches_rule("folder/one.txt", ["folder/one.txt"]))
        self.assertFalse(extension._matches_rule("folder/two.txt", ["folder/one.txt"]))
        self.assertFalse(extension._matches_rule("folder", ["folder/one.txt"]))

    def test_transient_metadata_read_keeps_last_valid_menu_jobs(self):
        extension = load_extension()
        job = {"id": "drive", "local_path": "/mnt/Cloud", "mode": "virtual_drive"}
        with patch.object(
            extension,
            "_state_document",
            return_value={"__tuxdrive__": {"nautilus_integration": True, "jobs": [job]}},
        ):
            self.assertEqual(extension._jobs(), [job])

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            extension, "_state_document", return_value={}
        ), patch.object(
            extension, "_config_path", return_value=Path(temporary) / "missing.json"
        ):
            self.assertEqual(extension._jobs(), [job])

    def test_transient_state_read_keeps_verified_badges(self):
        extension = load_extension()
        state = {
            "drive": {"offline_paths": ["folder/one.txt"]},
            "__tuxdrive__": {
                "nautilus_integration": True,
                "jobs": [{"id": "drive", "local_path": "/mnt/Cloud"}],
            },
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            extension, "_state_path", return_value=Path(temporary) / "state.json"
        ):
            path = extension._state_path()
            path.write_text(__import__("json").dumps(state), encoding="utf-8")
            self.assertEqual(extension._runtime_states()["drive"]["offline_paths"], ["folder/one.txt"])
            path.unlink()
            self.assertEqual(extension._runtime_states()["drive"]["offline_paths"], ["folder/one.txt"])

    def test_background_menu_cannot_trigger_recursive_offline_action(self):
        source = Path("packaging/nautilus-extension-tuxdrive.py").read_text(encoding="utf-8")
        self.assertIn("return self._menu_items(files, allow_availability=True)", source)
        self.assertIn(
            "return self._menu_items([current_folder], allow_availability=False)",
            source,
        )

    def test_completed_file_keeps_root_menu_and_exposes_online_only_action(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxDriveExtension)
        job = {
            "id": "drive",
            "local_path": "/mnt/Cloud",
            "mode": "virtual_drive",
            "offline_paths": ["folder/one.txt"],
            "online_only_paths": [],
        }
        path = Path("/mnt/Cloud/folder/one.txt")
        with patch.object(extension, "_jobs", return_value=[job]), patch.object(
            extension,
            "_runtime_states",
            return_value={
                "drive": {
                    "offline_paths": ["folder/one.txt"],
                    "configured_offline_paths": ["folder/one.txt"],
                    "online_only_paths": [],
                    "offline_pending_paths": [],
                }
            },
        ), patch.object(extension, "_local_path", return_value=path):
            menu = provider._menu_items([object()], allow_availability=True)

        self.assertEqual(len(menu), 1)
        self.assertEqual(menu[0].values["label"], "TuxDrive")
        labels = [item.values["label"] for item in menu[0].submenu.items]
        self.assertIn("Free local space (make online-only)", labels)

    def test_metadata_burst_is_coalesced_and_stale_handles_are_dropped_first(self):
        extension = load_extension()
        provider = object.__new__(extension.TuxDriveExtension)
        provider._invalidation_source = 0
        provider._known_files = {}
        changed = types.SimpleNamespace(get_basename=lambda: "nautilus-state.json")
        with patch.object(
            extension.GLib, "timeout_add", return_value=41, create=True
        ) as timeout_add:
            provider._metadata_changed(None, changed, None, None)
            provider._metadata_changed(None, changed, None, None)
        timeout_add.assert_called_once_with(200, provider._refresh_metadata)
        self.assertEqual(provider._invalidation_source, 41)

        class ReentrantFile:
            def invalidate_extension_info(inner_self):
                self.assertEqual(provider._known_files, {})

        provider._known_files = {"file:///one": ReentrantFile()}
        extension.GLib.SOURCE_REMOVE = False
        with patch.object(extension, "_state_document", return_value={}), patch.object(
            extension, "_jobs", return_value=[]
        ):
            self.assertFalse(provider._refresh_metadata())
        self.assertEqual(provider._known_files, {})


if __name__ == "__main__":
    unittest.main()
