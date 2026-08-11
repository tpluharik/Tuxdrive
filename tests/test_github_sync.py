import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tuxdrive.engine import SyncEngine
from tuxdrive.github_sync import GitHubSyncError, parse_repository_url, repository_item_url, validate_branch
from tuxdrive.models import SyncJob, SyncMode


class GitHubSyncTests(unittest.TestCase):
    def test_repository_urls_reject_embedded_tokens_and_non_github_hosts(self):
        self.assertEqual(parse_repository_url("git@github.com:owner/repo.git").name, "repo")
        self.assertEqual(parse_repository_url("https://github.com/owner/repo.git").owner, "owner")
        for value in (
            "https://token@github.com/owner/repo.git",
            "https://gitlab.com/owner/repo.git",
            "file:///tmp/repo",
        ):
            with self.assertRaises(GitHubSyncError):
                parse_repository_url(value)

    def test_branch_and_item_url_are_confined(self):
        self.assertEqual(validate_branch("feature/offline"), "feature/offline")
        with self.assertRaises(GitHubSyncError):
            validate_branch("../main")
        self.assertEqual(
            repository_item_url("https://github.com/owner/repo.git", "main", "docs/User Guide.md"),
            "https://github.com/owner/repo/tree/main/docs/User%20Guide.md",
        )

    def test_two_way_sync_stages_fetches_rebases_and_pushes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            job = SyncJob(
                account_remote="github-repo",
                local_path=str(root),
                repository_url="https://github.com/owner/repo.git",
                repository_branch="main",
                mode=SyncMode.TWO_WAY,
                git_author_name="TuxDrive Test",
                git_author_email="test@example.invalid",
            )
            engine = SyncEngine()
            commands = []

            def run(_job, command, _cwd, _log, _environment):
                commands.append(command)
                return 0

            with patch("tuxdrive.engine.shutil.which", return_value="/usr/bin/git"), \
                 patch.object(engine, "_run_git_process", side_effect=run), \
                 patch.object(
                     engine,
                     "_git_output",
                     side_effect=["https://github.com/owner/repo.git", "main"],
                 ), \
                 patch(
                     "tuxdrive.engine.subprocess.run",
                     side_effect=[
                         MagicMock(returncode=0, stdout="", stderr=""),
                         MagicMock(returncode=1, stdout="", stderr=""),
                     ],
                 ):
                result = engine._run_git_sync(job, root / "sync.log", False)
        self.assertTrue(result.success)
        self.assertTrue(any(command[3:5] == ["add", "-A"] for command in commands))
        self.assertTrue(any("commit" in command for command in commands))
        self.assertTrue(any("fetch" in command for command in commands))
        self.assertTrue(any("rebase" in command for command in commands))
        self.assertTrue(any("push" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
