"""Label reconciliation must preserve history and make drift visible."""

import io
import json
import unittest
from unittest.mock import MagicMock, patch

import sync_labels
from sync_labels import Label


class LabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.output = patch("sys.stdout", new=io.StringIO())
        self.output.start()
        self.addCleanup(self.output.stop)
        self.label: Label = {
            "name": "ci",
            "color": "ededed",
            "description": "Automation",
            "aliases": ["github_actions"],
        }
        self.current = {
            key: value for key, value in self.label.items() if key != "aliases"
        }

    def test_manifest_keeps_aliases_out_of_canonical_labels(self) -> None:
        labels = sync_labels.load_labels()
        names = {label["name"] for label in labels}
        self.assertIn("ci", names)
        self.assertNotIn("github_actions", names)

    @patch.object(sync_labels, "gh")
    def test_pagination_preserves_every_page(self, gh: MagicMock) -> None:
        gh.return_value = json.dumps([[{"number": 1}], [{"number": 2}]])
        self.assertEqual(sync_labels.pages("endpoint"), [{"number": 1}, {"number": 2}])
        gh.assert_called_once_with("api", "endpoint", "--paginate", "--slurp")

    @patch.object(sync_labels, "gh")
    def test_preview_only_reads_and_includes_closed_issues_and_prs(
        self, gh: MagicMock
    ) -> None:
        gh.side_effect = [
            json.dumps([[{"name": "github_actions"}]]),
            json.dumps(
                [
                    [{"number": 1, "state": "closed"}],
                    [{"number": 2, "pull_request": {}}],
                ]
            ),
        ]
        self.assertTrue(sync_labels.sync("owner/repo", [self.label], apply=False))
        self.assertEqual(gh.call_count, 2)
        self.assertIn("state=all&labels=github_actions", gh.call_args_list[-1].args[1])
        self.assertTrue(all("--method" not in call.args for call in gh.call_args_list))

    @patch.object(sync_labels, "gh")
    @patch.object(sync_labels, "pages")
    def test_merge_adds_canonical_label_before_deleting_alias(
        self, pages: MagicMock, gh: MagicMock
    ) -> None:
        pages.side_effect = [
            [self.current, {"name": "github_actions"}],
            [{"number": 1}, {"number": 2}],
        ]
        self.assertTrue(sync_labels.sync("owner/repo", [self.label], apply=True))
        self.assertEqual(gh.call_count, 3)
        for number, call in enumerate(gh.call_args_list[:2], start=1):
            self.assertEqual(
                call.args,
                ("api", f"repos/owner/repo/issues/{number}/labels", "--method", "POST"),
            )
            self.assertEqual(call.kwargs["payload"], {"labels": ["ci"]})
        self.assertEqual(
            gh.call_args_list[-1].args,
            ("api", "repos/owner/repo/labels/github_actions", "--method", "DELETE"),
        )

    @patch.object(sync_labels, "gh", side_effect=["", RuntimeError("failed")])
    @patch.object(sync_labels, "pages")
    def test_failed_assignment_never_deletes_historical_alias(
        self, pages: MagicMock, gh: MagicMock
    ) -> None:
        pages.side_effect = [
            [self.current, {"name": "github_actions"}],
            [{"number": 1}, {"number": 2}],
        ]
        with self.assertRaisesRegex(RuntimeError, "failed"):
            sync_labels.sync("owner/repo", [self.label], apply=True)
        self.assertTrue(all("DELETE" not in call.args for call in gh.call_args_list))

    @patch.object(sync_labels, "gh")
    @patch.object(sync_labels, "pages", return_value=[{"name": "unmanaged"}])
    def test_unknown_labels_fail_before_any_mutations(
        self, _pages: MagicMock, gh: MagicMock
    ) -> None:
        with self.assertRaisesRegex(ValueError, "Unmanaged labels"):
            sync_labels.sync("owner/repo", [self.label], apply=True)
        gh.assert_not_called()

    @patch.object(sync_labels, "gh")
    @patch.object(sync_labels, "pages")
    def test_create_update_and_idempotence(
        self, pages: MagicMock, gh: MagicMock
    ) -> None:
        pages.return_value = []
        self.assertTrue(sync_labels.sync("owner/repo", [self.label], apply=True))
        self.assertEqual(gh.call_args_list[-1].args[-1], "POST")
        pages.return_value = [{**self.current, "description": "Outdated"}]
        self.assertTrue(sync_labels.sync("owner/repo", [self.label], apply=True))
        self.assertEqual(gh.call_args_list[-1].args[-1], "PATCH")
        gh.reset_mock()
        pages.return_value = [self.current]
        self.assertFalse(sync_labels.sync("owner/repo", [self.label], apply=True))
        gh.assert_not_called()

    @patch.object(sync_labels, "sync", return_value=True)
    def test_check_fails_on_drift_without_writing(self, sync: MagicMock) -> None:
        with patch("sys.argv", ["sync_labels.py", "--check"]):
            self.assertEqual(sync_labels.main(), 1)
        self.assertFalse(sync.call_args_list[-1].kwargs["apply"])
        sync.return_value = False
        with patch("sys.argv", ["sync_labels.py", "--check"]):
            self.assertEqual(sync_labels.main(), 0)

    @patch.object(sync_labels, "pages")
    def test_invalid_repository_never_reaches_github(self, pages: MagicMock) -> None:
        with self.assertRaises(ValueError):
            sync_labels.sync("owner/repo?query", [self.label], apply=True)
        pages.assert_not_called()
