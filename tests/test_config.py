import json
import os
import tempfile
import unittest
from pathlib import Path

from tuxdrive.config import ConfigStore
from tuxdrive.models import Account, AppConfig, ConflictPolicy, PeerShare, Provider, SyncJob, SyncMode


class ConfigStoreTests(unittest.TestCase):
    def test_round_trip_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "config.json"
            store = ConfigStore(path)
            value = AppConfig(
                accounts=[Account("google-main", Provider.GOOGLE_DRIVE, "Work Drive")],
                jobs=[
                    SyncJob(
                        account_remote="google-main",
                        local_path="/tmp/cloud",
                        remote_path="Projects",
                        remote_scope="google-main,team_drive=drive-1,root_folder_id=",
                        cloud_location_name="Shared Drive · Projects",
                        acknowledge_google_abuse=True,
                        mode=SyncMode.TWO_WAY,
                        conflict_policy=ConflictPolicy.KEEP_BOTH,
                    )
                ],
                peer_shares=[PeerShare("Direct", "/tmp/direct", "192.0.2.4", 22022, "ssh-ed25519 AAAA")],
            )
            store.save(value)
            loaded = store.load()
            self.assertEqual(loaded.accounts[0].provider, Provider.GOOGLE_DRIVE)
            self.assertEqual(
                loaded.jobs[0].remote_spec,
                "google-main,team_drive=drive-1,root_folder_id=:Projects",
            )
            self.assertEqual(loaded.jobs[0].cloud_location_name, "Shared Drive · Projects")
            self.assertTrue(loaded.jobs[0].acknowledge_google_abuse)
            self.assertEqual(loaded.peer_shares[0].advertised_host, "192.0.2.4")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_profile_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(Path(temporary) / "config.json")
            value = AppConfig()
            value.settings.profile_remote = "google-main"
            value.settings.profile_last_backup = "2026-08-10T12:00:00+00:00"
            value.settings.language = "fr"
            store.save(value)
            loaded = store.load()
        self.assertEqual(loaded.settings.profile_remote, "google-main")
        self.assertEqual(loaded.settings.profile_last_backup, "2026-08-10T12:00:00+00:00")
        self.assertEqual(loaded.settings.language, "fr")

    def test_invalid_config_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                ConfigStore(path).load()
            self.assertTrue(path.with_suffix(".json.invalid").exists())


if __name__ == "__main__":
    unittest.main()
