import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        self.assertIn("--track-renames", command)
        self.assertEqual(command[command.index("--track-renames-strategy") + 1], "modtime,leaf")
        self.assertEqual(command[command.index("--max-delete") + 1], "25")

    def test_later_run_does_not_resync(self):
        job = SyncJob(account_remote="one", local_path="/data/One", initialized=True)
        self.assertNotIn("--resync", self.engine.command_for_job(job))

    def test_google_location_scope_is_used_in_sync_command(self):
        job = SyncJob(
            account_remote="google",
            remote_scope="google,team_drive=abc,root_folder_id=",
            local_path="/data/Drive",
            remote_path="Reports",
        )
        command = self.engine.command_for_job(job)
        self.assertEqual(command[3], "google,team_drive=abc,root_folder_id=:Reports")

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

    def test_google_abuse_failure_is_actionable_and_requires_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "sync.log"
            log.write_text(
                "ERROR : myweb/handy_switch.zip: Failed to copy: cannotDownloadAbusiveFile\n"
                "ERROR : Bisync aborted. Must run --resync to recover.\n",
                encoding="utf-8",
            )
            message = self.engine._failure_summary(log, 7)
            recovery = self.engine._requires_resync(log)
            blocked = self.engine._blocked_google_path(log)
        self.assertIn("myweb/handy_switch.zip", message)
        self.assertIn("suspected malware", message)
        self.assertTrue(recovery)
        self.assertEqual(blocked, "myweb/handy_switch.zip")

    def test_google_abuse_acknowledgement_is_opt_in(self):
        safe = SyncJob(account_remote="google", local_path="/data/Drive")
        allowed = SyncJob(
            account_remote="google",
            local_path="/data/Drive",
            acknowledge_google_abuse=True,
        )
        self.assertNotIn("--drive-acknowledge-abuse", self.engine.command_for_job(safe))
        self.assertIn("--drive-acknowledge-abuse", self.engine.command_for_job(allowed))

    def test_worker_replaces_incompatible_rclone_before_launch(self):
        job = SyncJob(account_remote="google", local_path="/data/Drive")
        completed = []
        process = MagicMock()
        process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxdrive.engine.resolve_rclone", return_value=None
        ), patch("tuxdrive.engine.install_rclone", return_value="/private/rclone"), patch(
            "tuxdrive.engine.subprocess.Popen", return_value=process
        ) as popen:
            self.engine._run_worker(
                job, Path(temporary) / "sync.log", completed.append, False
            )
        self.assertEqual(self.engine.rclone_path, "/private/rclone")
        self.assertEqual(popen.call_args.args[0][0], "/private/rclone")
        self.assertTrue(completed[0].success)


if __name__ == "__main__":
    unittest.main()
