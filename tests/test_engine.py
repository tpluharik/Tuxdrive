import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tuxdrive.engine import SyncEngine
from tuxdrive.callbacks import FileChange, FileState, changes_between, is_transient_path
from tuxdrive.models import (
    ConflictPolicy, SyncJob, SyncMode, paths_overlap, safe_streaming_overlap,
)


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

    def test_peer_lease_metadata_is_never_synchronized_as_user_content(self):
        job = SyncJob(account_remote="peer-team", local_path="/data/Team", peer_leases=True)
        command = self.engine.command_for_job(job)
        self.assertIn("/.tuxdrive-leases/**", command)

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
            self.assertEqual(command[command.index("--vfs-read-chunk-size") + 1], "8M")
            self.assertEqual(command[command.index("--vfs-cache-max-size") + 1], "10G")
            self.assertIn("--log-level", command)
            self.assertIn("--stats", command)

    def test_overlapping_sync_and_streaming_paths_are_detected(self):
        self.assertTrue(paths_overlap("/data/TuxDrive", "/data/TuxDrive/CEVRO"))
        self.assertTrue(paths_overlap("/data/TuxDrive/CEVRO", "/data/TuxDrive"))
        self.assertFalse(paths_overlap("/data/TuxDrive", "/data/StreamingDrive"))

    def test_streaming_child_is_safe_and_automatically_excluded_from_parent(self):
        parent = SyncJob(account_remote="google", local_path="/data/TuxDrive")
        streamed = SyncJob(
            account_remote="google",
            local_path="/data/TuxDrive/Online",
            mode=SyncMode.VIRTUAL_DRIVE,
        )
        self.assertTrue(safe_streaming_overlap(parent, streamed))
        self.assertFalse(safe_streaming_overlap(streamed, SyncJob(
            account_remote="google",
            local_path="/data/TuxDrive/Online/Downloaded",
        )))
        self.engine.configure_jobs([parent, streamed])
        command = self.engine.command_for_job(parent)
        self.assertIn("/Online/**", command)

    def test_streaming_mount_rejects_a_nonempty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            mountpoint = Path(temporary) / "mount"
            mountpoint.mkdir()
            (mountpoint / "existing").mkdir()
            job = SyncJob(
                account_remote="google",
                local_path=str(mountpoint),
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            result = self.engine.start_mount(job)
        self.assertFalse(result.success)
        self.assertIn("empty local folder", result.message)

    def test_startup_recovers_only_untracked_stale_streaming_mounts(self):
        stale = SyncJob(account_remote="google", local_path="/data/stale", mode=SyncMode.VIRTUAL_DRIVE)
        normal = SyncJob(account_remote="google", local_path="/data/normal")
        with patch("tuxdrive.engine.os.path.ismount", side_effect=lambda value: str(value) == "/data/stale"), \
             patch.object(self.engine, "_unmount_path", return_value=True) as unmount:
            recovered = self.engine.recover_stale_mounts([normal, stale])
        self.assertEqual(recovered, [stale.id])
        unmount.assert_called_once_with(stale.local)

    def test_unexpected_stream_exit_detaches_kernel_mount_before_retry(self):
        job = SyncJob(account_remote="google", local_path="/data/stream", mode=SyncMode.VIRTUAL_DRIVE)
        process = MagicMock()
        process.wait.return_value = 7
        self.engine._mounts[job.id] = process
        callback = MagicMock()
        with patch.object(self.engine, "_unmount_path", return_value=True) as unmount:
            self.engine._watch_mount(job, process, Path("/tmp/stream.log"), callback)
        unmount.assert_called_once_with(job.local)
        self.assertTrue(callback.call_args.args[0].mount_lost)

    def test_orderly_shutdown_also_detaches_streaming_mount(self):
        job = SyncJob(account_remote="google", local_path="/data/stream", mode=SyncMode.VIRTUAL_DRIVE)
        process = MagicMock(pid=1234)
        process.poll.return_value = None
        self.engine._mounts[job.id] = process
        self.engine._mount_paths[job.id] = job.local
        with patch("tuxdrive.engine.os.killpg"), \
             patch.object(self.engine, "_unmount_path", return_value=True) as unmount:
            self.engine.shutdown()
        unmount.assert_called_once_with(job.local)

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

    def test_incremental_commands_transfer_only_the_changed_path(self):
        job = SyncJob(account_remote="google", local_path="/data/Drive", remote_path="Docs")
        upload = self.engine._incremental_command(
            job, FileChange("Reports/result.pdf", "local")
        )
        download = self.engine._incremental_command(
            job, FileChange("Notes/today.txt", "remote")
        )
        deletion = self.engine._incremental_command(
            job, FileChange("old.txt", "local", deleted=True)
        )
        self.assertEqual(
            upload,
            ["/usr/bin/rclone", "copyto", "/data/Drive/Reports/result.pdf", "google:Docs/Reports/result.pdf"],
        )
        self.assertEqual(download[1], "copyto")
        self.assertEqual(download[-1], "/data/Drive/Notes/today.txt")
        self.assertEqual(deletion[1], "deletefile")

    def test_callback_delta_contains_only_created_changed_and_deleted_paths(self):
        previous = {
            "same.txt": FileState(1, "1"),
            "changed.txt": FileState(1, "1"),
            "deleted.txt": FileState(1, "1"),
        }
        current = {
            "same.txt": FileState(1, "1"),
            "changed.txt": FileState(2, "2"),
            "created.txt": FileState(3, "3"),
        }
        changes = changes_between(previous, current, "local")
        self.assertEqual(
            [(item.path, item.deleted) for item in changes],
            [("changed.txt", False), ("created.txt", False), ("deleted.txt", True)],
        )

    def test_office_lock_and_partial_files_are_never_synchronized(self):
        self.assertTrue(is_transient_path(".~lock.Cloud.pptx#"))
        self.assertTrue(is_transient_path("folder/~$Budget.xlsx"))
        self.assertTrue(is_transient_path("download.part"))
        job = SyncJob(account_remote="google", local_path="/data/Drive")
        self.assertIsNone(
            self.engine._incremental_command(
                job, FileChange(".~lock.Cloud.pptx#", "local")
            )
        )
        command = self.engine.command_for_job(job)
        self.assertIn(".~lock.*#", command)


if __name__ == "__main__":
    unittest.main()
