from __future__ import annotations

from collections.abc import Sequence

from .models import FolderGroup, SyncJob


def valid_group_id(group_id: str, groups: Sequence[FolderGroup]) -> str:
    """Return a persisted group id only when it still names a real group."""
    return group_id if group_id and any(group.id == group_id for group in groups) else ""


def move_job(
    jobs: list[SyncJob],
    groups: Sequence[FolderGroup],
    job_id: str,
    target_group_id: str,
    *,
    anchor_job_id: str = "",
    after: bool = False,
) -> bool:
    """Move one display entry without touching either endpoint's filesystem paths.

    ``jobs`` is the persisted display order. An anchor places the moved job before
    or after another visible entry. Dropping on a group header (no anchor) appends
    it to that group's current entries.
    """
    source = next((job for job in jobs if job.id == job_id), None)
    if source is None or (anchor_job_id and anchor_job_id == job_id):
        return False

    group_id = valid_group_id(target_group_id, groups)
    anchor = next((job for job in jobs if job.id == anchor_job_id), None)
    if anchor is not None:
        group_id = valid_group_id(anchor.group_id, groups)

    previous_group = source.group_id
    previous_index = jobs.index(source)
    jobs.pop(previous_index)
    source.group_id = group_id

    if anchor is not None and anchor in jobs:
        index = jobs.index(anchor) + (1 if after else 0)
    else:
        members = [
            index for index, job in enumerate(jobs)
            if valid_group_id(job.group_id, groups) == group_id
        ]
        index = members[-1] + 1 if members else len(jobs)
    jobs.insert(index, source)
    return previous_group != source.group_id or previous_index != jobs.index(source)
