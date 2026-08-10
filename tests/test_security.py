import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tuxdrive.security import UnsafePathError, confined_path, sign_json, verify_signed_json


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


if __name__ == "__main__":
    unittest.main()
