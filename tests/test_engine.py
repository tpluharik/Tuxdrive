import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from tuxdrive.engine import JobResult, SyncEngine
from tuxdrive.callbacks import FileChange, FileState, changes_between, is_transient_path
from tuxdrive.models import (
    ConflictPolicy, PeerRole, SyncJob, SyncMode, paths_overlap, safe_streaming_overlap,
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

    def test_peer_roles_constrain_full_and_incremental_direction(self):
        read_only = SyncJob(account_remote="peer", local_path="/data/Peer", mode=SyncMode.DOWNLOAD_ONLY, peer_role=PeerRole.READ_ONLY)
        receive = SyncJob(account_remote="peer", local_path="/data/Peer", mode=SyncMode.DOWNLOAD_ONLY, peer_role=PeerRole.RECEIVE_ONLY)
        send = SyncJob(account_remote="peer", local_path="/data/Peer", mode=SyncMode.UPLOAD_ONLY, peer_role=PeerRole.SEND_ONLY)
        self.assertEqual(self.engine.command_for_job(read_only)[1], "copy")
        self.assertEqual(self.engine.command_for_job(receive)[1], "sync")
        self.assertIsNone(self.engine._incremental_command(read_only, FileChange("local.txt", "local", False)))
        self.assertIsNone(self.engine._incremental_command(send, FileChange("remote.txt", "remote", False)))
        self.assertEqual(self.engine._incremental_command(send, FileChange("local.txt", "local", False))[1], "copyto")

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
            self.assertEqual(command[command.index("--vfs-cache-max-age") + 1], "87600h")
            self.assertEqual(command[command.index("--vfs-cache-max-size") + 1], "off")
            self.assertEqual(command[command.index("--vfs-cache-min-free-space") + 1], "off")
            self.assertIn("--vfs-fast-fingerprint", command)
            self.assertIn("--log-level", command)
            self.assertIn("--stats", command)

    def test_pin_state_never_changes_live_mount_policy(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_CACHE_HOME": temporary}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Google",
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["projects/rail"],
            )
            command = self.engine.mount_command(job)
            job.offline_paths.clear()
            online_only_command = self.engine.mount_command(job)
        self.assertEqual(command, online_only_command)

    def test_offline_root_and_file_are_fully_hydrated_and_persisted(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "folder").mkdir()
            (root / "folder" / "one.bin").write_bytes(b"one")
            (root / "two.bin").write_bytes(b"two")
            job = SyncJob(
                account_remote="google",
                local_path=str(root),
                remote_path="RemoteRoot",
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            cached = Path(cache) / "tuxdrive" / "vfs" / job.id / "vfs" / "google" / "RemoteRoot" / "folder"
            cached.mkdir(parents=True)
            (cached / "one.bin").write_bytes(b"one")
            (cached.parent / "two.bin").write_bytes(b"two")
            message = self.engine.set_offline(job, ".", True)
            verified = self.engine.verified_offline_rules(job)
        self.assertEqual(job.offline_paths, ["."])
        self.assertEqual(verified, {"."})
        self.assertIn("2 file(s)", message)
        self.assertIn("6 bytes", message)

    def test_offline_parent_rule_replaces_redundant_children(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "folder" / "child").mkdir(parents=True)
            (root / "folder" / "child" / "one.bin").write_bytes(b"one")
            job = SyncJob(
                account_remote="google",
                local_path=str(root),
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["folder/child"],
            )
            cached = Path(cache) / "tuxdrive" / "vfs" / job.id / "vfs" / "google" / "folder" / "child"
            cached.mkdir(parents=True)
            (cached / "one.bin").write_bytes(b"one")
            self.engine.set_offline(job, "folder", True)
        self.assertEqual(job.offline_paths, ["folder"])

    def test_single_file_pin_waits_for_rclone_cache_publication(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "folder").mkdir()
            source = root / "folder" / "one.bin"
            source.write_bytes(b"one")
            job = SyncJob(
                account_remote="google,team_drive=,root_folder_id=root",
                local_path=str(root),
                remote_path="RemoteRoot",
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            cached = (
                Path(cache) / "tuxdrive" / "vfs" / job.id / "vfs" /
                "google,team_drive=,root_folder_id=root" / "RemoteRoot" / "folder" / "one.bin"
            )

            def publish_cache() -> None:
                time.sleep(0.05)
                cached.parent.mkdir(parents=True)
                cached.write_bytes(b"one")

            publisher = threading.Thread(target=publish_cache)
            publisher.start()
            try:
                message = self.engine.set_offline(job, "folder/one.bin", True)
            finally:
                publisher.join()
            self.assertEqual(job.offline_paths, ["folder/one.bin"])
            self.assertEqual(self.engine.verified_offline_rules(job), {"folder/one.bin"})
            self.assertIn("1 file(s)", message)

    def test_online_only_child_overrides_parent_and_releases_matching_cache(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "folder").mkdir()
            (root / "folder" / "online.bin").write_bytes(b"online")
            (root / "folder" / "kept.bin").write_bytes(b"kept")
            job = SyncJob(
                account_remote="google",
                local_path=str(root),
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["folder"],
            )
            cache_files = Path(cache) / "tuxdrive" / "vfs" / job.id / "vfs" / "google" / "folder"
            cache_files.mkdir(parents=True)
            (cache_files / "online.bin").write_bytes(b"online")
            (cache_files / "kept.bin").write_bytes(b"kept")
            message = self.engine.set_offline(job, "folder/online.bin", False)
            self.assertFalse((cache_files / "online.bin").exists())
            self.assertTrue((cache_files / "kept.bin").exists())
        self.assertEqual(job.offline_paths, ["folder"])
        self.assertEqual(job.online_only_paths, ["folder/online.bin"])
        self.assertIn("Online only", message)

    def test_online_only_root_clears_rules_cache_and_markers(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "one.bin").write_bytes(b"one")
            job = SyncJob(account_remote="google", local_path=str(root), mode=SyncMode.VIRTUAL_DRIVE)
            cached = Path(cache) / "tuxdrive" / "vfs" / job.id / "vfs" / "google"
            cached.mkdir(parents=True)
            (cached / "one.bin").write_bytes(b"one")
            self.engine.set_offline(job, ".", True)
            cache_root = Path(cache) / "tuxdrive" / "vfs" / job.id
            self.assertTrue((cache_root / ".tuxdrive-pins").exists())
            self.engine.set_offline(job, ".", False)
            self.assertFalse(cache_root.exists())
        self.assertEqual(job.offline_paths, [])
        self.assertEqual(job.online_only_paths, [])

    def test_old_pin_without_marker_is_not_downloaded_or_verified(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Google",
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["."],
            )
            with patch.object(
                self.engine, "set_offline", side_effect=AssertionError("mount must not be read")
            ):
                verified = self.engine.verified_offline_rules(job)
        self.assertEqual(verified, set())

    def test_tampered_pin_marker_cannot_escape_cache_root(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Google",
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["folder"],
            )
            marker = self.engine._pin_marker(job, "folder")
            marker.parent.mkdir(parents=True)
            marker.write_text(
                '{"relative":"folder","files":[{"path":"../../outside","size":1,"blocks":1}]}',
                encoding="utf-8",
            )
            self.assertEqual(self.engine.verified_offline_rules(job), set())

    def test_restart_mount_applies_changed_vfs_policy(self):
        job = SyncJob(
            account_remote="google",
            local_path="/mnt/Google",
            mode=SyncMode.VIRTUAL_DRIVE,
            offline_paths=["folder"],
        )
        expected = JobResult(job.id, True, "mounted", Path("/tmp/mount.log"))
        callback = Mock()
        with patch.object(self.engine, "stop_mount", return_value=True) as stop, \
             patch.object(self.engine, "start_mount", return_value=expected) as start:
            result = self.engine.restart_mount(job, callback)
        self.assertIs(result, expected)
        stop.assert_called_once_with(job)
        start.assert_called_once_with(job)

    def test_failed_offline_symlink_hydration_rolls_back_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root.parent / "outside-tuxdrive-test"
            outside.write_text("secret", encoding="utf-8")
            try:
                (root / "escape").symlink_to(outside)
                job = SyncJob(account_remote="google", local_path=str(root), mode=SyncMode.VIRTUAL_DRIVE)
                with self.assertRaises(ValueError):
                    self.engine.set_offline(job, "escape", True)
                self.assertEqual(job.offline_paths, [])
            finally:
                outside.unlink(missing_ok=True)

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
