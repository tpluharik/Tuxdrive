import json
import tempfile
import unittest
from pathlib import Path

from tuxdrive.config import ConfigStore
from tuxdrive.migration import MigrationError, ProfileManager, decrypt_profile, encrypt_profile
from tuxdrive.models import Account, AppConfig, Provider, SyncJob


class FakeRclone:
    def __init__(self, root: Path):
        self.root = root
        self.config = root / "rclone.conf"
        self.config.write_text("[google]\ntype = drive\ntoken = secret\n", encoding="utf-8")

    def config_file(self):
        return self.config

    def _path(self, spec):
        remote, path = str(spec).split(":", 1)
        return self.root / "cloud" / remote / path

    def copy_to(self, source, destination):
        source_path = Path(source) if ":" not in str(source) else self._path(source)
        destination_path = Path(destination) if ":" not in str(destination) else self._path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(source_path.read_bytes())

    def object_exists(self, spec):
        return self._path(spec).is_file()


class MigrationTests(unittest.TestCase):
    def test_encryption_round_trip_and_wrong_password(self):
        data = encrypt_profile({"answer": 42}, "a-secure-password")
        self.assertEqual(decrypt_profile(data, "a-secure-password"), {"answer": 42})
        self.assertNotIn(b"answer", data)
        with self.assertRaises(MigrationError):
            decrypt_profile(data, "wrong-password")

    def test_tampering_is_rejected(self):
        data = json.loads(encrypt_profile({"safe": True}, "a-secure-password"))
        data["ciphertext"] = data["ciphertext"][:-2] + "AA"
        with self.assertRaises(MigrationError):
            decrypt_profile(json.dumps(data).encode(), "a-secure-password")

    def test_profile_upload_inspect_and_restore_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ConfigStore(root / "config.json")
            manager = ProfileManager(store, FakeRclone(root), root / "peer")
            config = AppConfig(
                accounts=[Account("google", Provider.GOOGLE_DRIVE, "Personal")],
                jobs=[SyncJob(account_remote="google", local_path="/tmp/Drive", remote_path="Projects")],
            )
            summary = manager.upload("google", config, "a-secure-password")
            self.assertTrue(manager.available("google"))
            self.assertEqual((summary.accounts, summary.jobs), (1, 1))
            restored = manager.restore(manager.download("google"), "a-secure-password")
            self.assertEqual(restored.jobs[0].remote_path, "Projects")
            self.assertEqual(store.load().accounts[0].display_name, "Personal")

    def test_credentials_are_opt_in_and_restore_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            peer = root / "peer"
            peer.mkdir()
            (peer / "identity").write_text("private-key", encoding="utf-8")
            rclone = FakeRclone(root)
            store = ConfigStore(root / "config.json")
            manager = ProfileManager(store, rclone, peer)
            plain = manager.create_bytes(AppConfig(), "a-secure-password", False)
            self.assertNotIn("secrets", decrypt_profile(plain, "a-secure-password"))
            protected = manager.create_bytes(AppConfig(), "a-secure-password", True)
            rclone.config.write_text("changed", encoding="utf-8")
            (peer / "identity").unlink()
            manager.restore(protected, "a-secure-password", restore_credentials=True)
            self.assertIn("token = secret", rclone.config.read_text(encoding="utf-8"))
            self.assertEqual((peer / "identity").read_text(encoding="utf-8"), "private-key")
            self.assertEqual(rclone.config.stat().st_mode & 0o777, 0o600)

    def test_remote_name_and_short_password_are_rejected(self):
        with self.assertRaises(MigrationError):
            ProfileManager.remote_spec("bad:remote")
        with self.assertRaises(MigrationError):
            encrypt_profile({}, "short")


if __name__ == "__main__":
    unittest.main()
