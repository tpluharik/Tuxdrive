import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tuxdrive.callbacks import FileChange
from tuxdrive.models import SyncJob
from tuxdrive.recovery import IntegrityAuditor, MassChangeGuard, RecoveryManager


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

    def test_mass_change_and_ransomware_suffixes_pause_job(self):
        self.job.mass_change_limit = 3
        changes = [FileChange(f"file-{index}.txt", "local") for index in range(3)]
        self.assertTrue(MassChangeGuard.assess(self.job, changes, 100).blocked)
        encrypted = [FileChange(f"victim-{index}.locked", "local") for index in range(5)]
        self.assertTrue(MassChangeGuard.assess(self.job, encrypted, 100).blocked)

    @mock.patch("tuxdrive.recovery.subprocess.run")
    def test_integrity_audit_parses_actionable_differences(self, run):
        run.return_value = mock.Mock(returncode=1, stdout="= same\n* changed\n+ local\n- cloud\n", stderr="")
        auditor = IntegrityAuditor("rclone", self.manager)
        issues = auditor.audit(self.job)
        self.assertEqual([(item.symbol, item.path) for item in issues], [("*", "changed"), ("+", "local"), ("-", "cloud")])


if __name__ == "__main__":
    unittest.main()
