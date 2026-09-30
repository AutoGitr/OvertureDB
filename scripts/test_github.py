"""PR creation keeps untrusted text in arguments and preserves review boundaries."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import github


class PullRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        output = patch("sys.stdout", new=io.StringIO())
        output.start()
        self.addCleanup(output.stop)

    def publish(self) -> str | None:
        return github.create_pull_request(
            "owner/repo",
            branch="contribution/issue-12",
            title="Dataset selection",
            body="Review `code` and $(literal text).\n\nCloses #12\n",
            files=["data/movies/tmdb-1.json"],
            labels=["contribution", "movie"],
        )

    @patch.object(github, "git")
    @patch.object(github, "gh")
    def test_body_labels_and_file_scope_survive_publication(
        self, gh: MagicMock, git: MagicMock
    ) -> None:
        git.return_value = " M data/movies/tmdb-1.json"
        bodies: list[str] = []

        def command(*args: str) -> str:
            if args[:2] == ("pr", "create"):
                bodies.append(Path(args[args.index("--body-file") + 1]).read_text())
                return "https://github.com/owner/repo/pull/1"
            return ""

        gh.side_effect = command
        self.assertEqual(self.publish(), "https://github.com/owner/repo/pull/1")
        self.assertEqual(bodies, ["Review `code` and $(literal text).\n\nCloses #12\n"])
        self.assertIn(call("add", "--", "data/movies/tmdb-1.json"), git.call_args_list)
        self.assertEqual(
            git.call_args_list[-1], call("push", "origin", "contribution/issue-12")
        )
        self.assertEqual(
            gh.call_args_list[-1].args[-4:],
            ("--label", "contribution", "--label", "movie"),
        )

    @patch.object(github, "git")
    @patch.object(github, "gh", return_value="https://github.com/owner/repo/pull/1")
    def test_existing_pr_never_creates_another_or_changes_git(
        self, gh: MagicMock, git: MagicMock
    ) -> None:
        self.assertIsNone(self.publish())
        git.assert_not_called()
        self.assertEqual(gh.call_count, 1)

    @patch.object(github, "git", return_value="")
    @patch.object(github, "gh", return_value="")
    def test_unchanged_data_never_commits_or_pushes(
        self, gh: MagicMock, git: MagicMock
    ) -> None:
        self.assertIsNone(self.publish())
        git.assert_called_once_with(
            "status", "--porcelain", "--", "data/movies/tmdb-1.json"
        )
        self.assertEqual(gh.call_count, 1)

    @patch.object(github, "git")
    @patch.object(github, "gh", return_value="")
    def test_git_failure_stops_before_pr_creation(
        self, gh: MagicMock, git: MagicMock
    ) -> None:
        git.side_effect = ["changed", RuntimeError("checkout failed")]
        with self.assertRaisesRegex(RuntimeError, "checkout failed"):
            self.publish()
        self.assertNotIn(("pr", "create"), [c.args[:2] for c in gh.call_args_list])

    @patch.object(github, "gh", return_value="")
    def test_publication_commit_excludes_unrelated_staged_files(
        self, _gh: MagicMock
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(github, "ROOT", root):
                github.git("init", "-q")
                github.git("config", "user.name", "Test")
                github.git("config", "user.email", "test@example.com")
                github.git("config", "commit.gpgsign", "false")
                unrelated = root / "unrelated.txt"
                unrelated.write_text("original", encoding="utf-8")
                github.git("add", "unrelated.txt")
                github.git("commit", "-qm", "base")
                unrelated.write_text("staged change", encoding="utf-8")
                github.git("add", "unrelated.txt")
                target = root / "data/movies/tmdb-1.json"
                target.parent.mkdir(parents=True)
                target.write_text("{}", encoding="utf-8")
                git = github.git

                def local_git(*args: str) -> str:
                    return "" if args[0] == "push" else git(*args)

                with patch.object(github, "git", side_effect=local_git):
                    self.publish()
                self.assertEqual(
                    github.git("diff", "HEAD~1", "HEAD", "--name-only"),
                    "data/movies/tmdb-1.json",
                )
                self.assertEqual(
                    github.git("diff", "--cached", "--name-only"), "unrelated.txt"
                )
