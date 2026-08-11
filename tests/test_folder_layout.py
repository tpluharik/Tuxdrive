import unittest

from tuxdrive.folder_layout import (
    job_drag_payload,
    job_id_from_drag_payload,
    move_job,
    valid_group_id,
)
from tuxdrive.models import FolderGroup, SyncJob


def job(name: str, group_id: str = "") -> SyncJob:
    return SyncJob("remote", f"/tmp/{name}", name=name, group_id=group_id, id=name)


class FolderLayoutTests(unittest.TestCase):
    def setUp(self):
        self.work = FolderGroup("Work", id="work")
        self.personal = FolderGroup("Personal", id="personal")
        self.groups = [self.work, self.personal]

    def test_reorders_job_before_visible_anchor(self):
        jobs = [job("one", "work"), job("two", "work"), job("three", "work")]
        self.assertTrue(move_job(jobs, self.groups, "three", "work", anchor_job_id="one"))
        self.assertEqual([item.id for item in jobs], ["three", "one", "two"])
        self.assertEqual(jobs[0].group_id, "work")

    def test_reorders_job_after_visible_anchor(self):
        jobs = [job("one", "work"), job("two", "work"), job("three", "work")]
        self.assertTrue(move_job(jobs, self.groups, "one", "work", anchor_job_id="two", after=True))
        self.assertEqual([item.id for item in jobs], ["two", "one", "three"])

    def test_drop_on_group_moves_and_appends_without_changing_paths(self):
        jobs = [job("one", "work"), job("two", "personal"), job("three", "work")]
        original_path = jobs[1].local_path
        self.assertTrue(move_job(jobs, self.groups, "two", "work"))
        self.assertEqual([item.id for item in jobs], ["one", "three", "two"])
        self.assertEqual(jobs[-1].group_id, "work")
        self.assertEqual(jobs[-1].local_path, original_path)

    def test_drop_on_ungrouped_header_moves_to_ungrouped_tail(self):
        jobs = [job("loose"), job("one", "work"), job("two", "work")]
        self.assertTrue(move_job(jobs, self.groups, "one", ""))
        self.assertEqual([item.id for item in jobs], ["loose", "one", "two"])
        self.assertEqual(jobs[1].group_id, "")

    def test_anchor_defines_destination_group(self):
        jobs = [job("one", "work"), job("two", "personal")]
        self.assertTrue(move_job(jobs, self.groups, "one", "work", anchor_job_id="two"))
        self.assertEqual(jobs[0].id, "one")
        self.assertEqual(jobs[0].group_id, "personal")

    def test_unknown_group_is_safely_ungrouped(self):
        groups = [FolderGroup("Work", id="work")]
        self.assertEqual(valid_group_id("deleted", groups), "")
        jobs = [job("one", "work"), job("two", "deleted")]
        self.assertTrue(move_job(jobs, groups, "one", "deleted"))
        self.assertEqual(jobs[-1].group_id, "")

    def test_self_drop_is_noop(self):
        jobs = [job("one", "work")]
        self.assertFalse(move_job(jobs, self.groups, "one", "work", anchor_job_id="one"))
        self.assertEqual([item.id for item in jobs], ["one"])

    def test_drag_payload_round_trip_uses_recognizable_text(self):
        payload = job_drag_payload("folder-id")
        self.assertEqual(payload, "tuxdrive-job:folder-id")
        self.assertEqual(job_id_from_drag_payload(payload), "folder-id")
        self.assertEqual(job_id_from_drag_payload(payload.encode("utf-8")), "folder-id")

    def test_drag_payload_rejects_unrelated_or_malformed_text(self):
        self.assertEqual(job_id_from_drag_payload("folder-id"), "")
        self.assertEqual(job_id_from_drag_payload(b"\xff"), "")
        self.assertEqual(job_id_from_drag_payload("tuxdrive-job:"), "")
        self.assertEqual(job_drag_payload("bad\x00id"), "")


if __name__ == "__main__":
    unittest.main()
