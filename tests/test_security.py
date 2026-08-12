import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tuxindrive.security import (
    UnsafePathError, confined_path, copy_from_confined, install_confined,
    sign_json, unlink_confined, verify_signed_json,
)


class SecurityBoundaryTests(unittest.TestCase):
    def test_confined_path_rejects_parent_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, outside = base / "root", base / "outside"
            root.mkdir(); outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(UnsafePathError):
                confined_path(root, "../outside/file")
            with self.assertRaises((UnsafePathError, OSError)):
                confined_path(root, "link/file", create_parents=True)

    def test_signed_json_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Ed25519PrivateKey.generate()
            path = Path(temporary) / "identity"
            path.write_bytes(private.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            ))
            value = {"path": "document.odt", "size": 42}
            public, signature = sign_json(value, path)
            verify_signed_json(value, public, signature)
            with self.assertRaises(Exception):
                verify_signed_json({**value, "size": 43}, public, signature)

    def test_windows_confined_file_operations_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.security.platform.system", return_value="Windows"
        ):
            base = Path(temporary)
            root = base / "root"
            root.mkdir()
            source = base / "source"
            source.write_bytes(b"portable payload")
            installed = install_confined(source, root, "folder/file.bin")
            self.assertEqual(installed.read_bytes(), b"portable payload")
            exported = base / "exported"
            copy_from_confined(root, "folder/file.bin", exported)
            self.assertEqual(exported.read_bytes(), b"portable payload")
            unlink_confined(root, "folder/file.bin")
            self.assertFalse(installed.exists())

    def test_windows_confined_path_rejects_reparse_parent(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.security.platform.system", return_value="Windows"
        ):
            base = Path(temporary)
            root, outside = base / "root", base / "outside"
            root.mkdir(); outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(UnsafePathError):
                confined_path(root, "link/file.bin", create_parents=True)


if __name__ == "__main__":
    unittest.main()
