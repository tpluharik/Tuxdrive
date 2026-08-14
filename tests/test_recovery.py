import tempfile
import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tuxindrive.callbacks import FileChange
from tuxindrive.models import SyncJob
from tuxindrive.recovery import (
    IntegrityAuditor, MassChangeGuard, RecoveryEntry, RecoveryManager, SafetyError,
)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.local = self.root / "local"
        self.local.mkdir()
        self.job = SyncJob(account_remote="cloud", local_path=str(self.local), initialized=True)
        self.manager = RecoveryManager(self.root / "history")

    def tearDown(self):
        self.temporary.cleanup()

    def test_deleted_file_can_be_restored(self):
        source = self.local / "folder" / "draft.txt"
        source.parent.mkdir()
        source.write_text("before", encoding="utf-8")
        entry = self.manager.archive_local(self.job, "folder/draft.txt", "remote deletion")
        source.unlink()
        restored = self.manager.restore(self.job, entry)
        self.assertEqual(restored.read_text(encoding="utf-8"), "before")
        self.assertEqual(len(self.manager.entries(self.job.id)), 1)

    def test_disabled_history_does_not_archive_incoming_changes(self):
        self.job.version_history = False
        source = self.local / "draft.txt"
        source.write_text("before", encoding="utf-8")
        archived = self.manager.archive_incoming_changes(
            self.job, [FileChange("draft.txt", "remote", deleted=True)],
        )
        self.assertEqual(archived, [])
        self.assertFalse((self.root / "history" / self.job.id).exists())

    def test_entries_ignore_malformed_or_missing_history_records(self):
        index = self.root / "history" / self.job.id / "index.jsonl"
        index.parent.mkdir(parents=True)
        index.write_text('{"missing":"fields"}\nnot-json\n', encoding="utf-8")
        self.assertEqual(self.manager.entries(self.job.id), [])

    def test_restore_rejects_foreign_job_and_unsafe_relative_path(self):
        stored = self.root / "stored"
        stored.write_bytes(b"history")
        now = datetime.now(timezone.utc).isoformat()
        foreign = RecoveryEntry("other", "file", str(stored), now, "test", 7)
        with self.assertRaisesRegex(SafetyError, "no longer available"):
            self.manager.restore(self.job, foreign)
        unsafe = RecoveryEntry(self.job.id, "../escape", str(stored), now, "test", 7)
        with self.assertRaisesRegex(SafetyError, "unsafe"):
            self.manager.restore(self.job, unsafe)

    def test_prune_removes_only_expired_versions(self):
        job_root = self.root / "history" / self.job.id
        old_file, new_file = job_root / "old", job_root / "new"
        job_root.mkdir(parents=True)
        old_file.write_bytes(b"old")
        new_file.write_bytes(b"new")
        old = RecoveryEntry(
            self.job.id, "old.txt", str(old_file),
            (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(), "test", 3,
        )
        new = RecoveryEntry(
            self.job.id, "new.txt", str(new_file),
            datetime.now(timezone.utc).isoformat(), "test", 3,
        )
        index = job_root / "index.jsonl"
        index.write_text("\n".join(json.dumps({field: getattr(item, field) for field in item.__dataclass_fields__}) for item in (old, new)) + "\n", encoding="utf-8")
        self.assertEqual(self.manager.prune(self.job), 1)
        self.assertFalse(old_file.exists())
        self.assertTrue(new_file.exists())
        self.assertEqual([entry.relative_path for entry in self.manager.entries(self.job.id)], ["new.txt"])

    def test_mass_change_and_ransomware_suffixes_pause_job(self):
        self.job.mass_change_limit = 3
        changes = [FileChange(f"file-{index}.txt", "local") for index in range(3)]
        self.assertTrue(MassChangeGuard.assess(self.job, changes, 100).blocked)
        encrypted = [FileChange(f"victim-{index}.locked", "local") for index in range(5)]
        self.assertTrue(MassChangeGuard.assess(self.job, encrypted, 100).blocked)

    def test_mass_change_log_parsing_respects_disabled_protection(self):
        log = self.root / "preview.log"
        log.write_text("NOTICE : folder/file.txt: Deleted\n", encoding="utf-8")
        self.job.ransomware_protection = False
        self.assertFalse(MassChangeGuard.assess_log(self.job, log, 1).blocked)

    @mock.patch("tuxindrive.recovery.subprocess.run")
    def test_integrity_audit_parses_actionable_differences(self, run):
        run.return_value = mock.Mock(returncode=1, stdout="= same\n* changed\n+ local\n- cloud\n", stderr="")
        auditor = IntegrityAuditor("rclone", self.manager)
        issues = auditor.audit(self.job)
        self.assertEqual([(item.symbol, item.path) for item in issues], [("*", "changed"), ("+", "local"), ("-", "cloud")])


if __name__ == "__main__":
    unittest.main()
