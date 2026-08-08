import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxdrive.engine import SyncEngine
from tuxdrive.models import ConflictPolicy, SyncJob, SyncMode


class SyncEngineCommandTests(unittest.TestCase):
    def setUp(self):
        self.engine = SyncEngine("/usr/bin/rclone")

    def test_first_two_way_run_is_safe_resync(self):
        job = SyncJob(
            account_remote="google",
            local_path="/data/Drive",
            remote_path="Team",
            conflict_policy=ConflictPolicy.KEEP_BOTH,
            initialized=False,
            max_delete=25,
        )
        command = self.engine.command_for_job(job)
        self.assertEqual(command[:4], ["/usr/bin/rclone", "bisync", "/data/Drive", "google:Team"])
        self.assertIn("--resync", command)
        self.assertIn("pathname", command)
        self.assertEqual(command[command.index("--max-delete") + 1], "25")

    def test_later_run_does_not_resync(self):
        job = SyncJob(account_remote="one", local_path="/data/One", initialized=True)
        self.assertNotIn("--resync", self.engine.command_for_job(job))

    def test_one_way_direction(self):
        download = SyncJob(
            account_remote="one",
            local_path="/data/One",
            remote_path="Docs",
            mode=SyncMode.DOWNLOAD_ONLY,
        )
        upload = SyncJob(
            account_remote="one",
            local_path="/data/One",
            remote_path="Docs",
            mode=SyncMode.UPLOAD_ONLY,
        )
        self.assertEqual(self.engine.command_for_job(download)[2:4], ["one:Docs", "/data/One"])
        self.assertEqual(self.engine.command_for_job(upload)[2:4], ["/data/One", "one:Docs"])

    def test_virtual_drive_uses_full_vfs_cache(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_CACHE_HOME": temporary}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Google",
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            command = self.engine.mount_command(job)
            self.assertEqual(command[:4], ["/usr/bin/rclone", "mount", "google:", "/mnt/Google"])
            self.assertEqual(command[command.index("--vfs-cache-mode") + 1], "full")

    def test_failure_summary_surfaces_fatal_detail(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = os.path.join(temporary, "sync.log")
            with open(log, "w", encoding="utf-8") as handle:
                handle.write("Usage:\nFatal error: unknown flag: --resilient\n")
            message = self.engine._failure_summary(Path(log), 1)
        self.assertEqual(message, "Synchronization failed: unknown flag: --resilient")


if __name__ == "__main__":
    unittest.main()
