import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def load_extension():
    gi = types.ModuleType("gi")
    repository = types.ModuleType("gi.repository")
    repository.Gio = types.SimpleNamespace()
    repository.GLib = types.SimpleNamespace()
    repository.GObject = types.SimpleNamespace(GObject=type("GObject", (), {}))
    repository.Nautilus = types.SimpleNamespace(
        MenuProvider=type("MenuProvider", (), {}),
        InfoProvider=type("InfoProvider", (), {}),
        FileInfo=object,
        MenuItem=object,
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


if __name__ == "__main__":
    unittest.main()
