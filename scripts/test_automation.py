"""Security boundaries for public issue input and privileged automation."""

import copy
import io
import json
import tempfile
import unittest
from http.client import HTTPMessage
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.request import Request
from zipfile import ZipFile

import automation
import catalog
from contribution import clean_youtube_id, parse_issue_form
from guard import validate_changes
from import_bulk_export import import_bulk_export, load_incoming_entries
from test_catalog import movie


def issue(**changes: Any) -> dict[str, Any]:
    return {
        "number": 12,
        "state": "open",
        "body": "body",
        "title": "Title",
        "labels": [{"name": "contribution"}, {"name": "movie"}],
        "updated_at": "2026-09-23T10:00:00Z",
        **changes,
    }


class CommandTests(unittest.TestCase):
    @patch.object(automation, "gh", return_value="")
    @patch.object(automation, "api")
    def test_rejection_uses_api_state_reason(
        self, api: MagicMock, gh: MagicMock
    ) -> None:
        api.side_effect = [{"permission": "write"}, issue(), {}, {}]
        event = self.event()
        event["comment"]["body"] = "@OvertureDB-bot reject wrong artwork"
        automation.gate(event, "owner/repo")
        self.assertEqual(
            gh.call_args_list[-1].kwargs["payload"],
            {
                "state": "closed",
                "state_reason": "not_planned",
            },
        )
        self.assertEqual(
            api.call_args_list[-1].args[0], "repos/owner/repo/issues/12/comments"
        )

    def test_identifier_urls_require_real_provider_hosts(self) -> None:
        for heading, value in (
            ("TMDB ID", "https://evil.test/themoviedb.org/movie/123"),
            ("TVDB ID", "https://notthetvdb.com/series/123"),
            ("IMDb ID", "unrelated-tt123-suffix"),
        ):
            with self.subTest(heading=heading), self.assertRaises(ValueError):
                parse_issue_form(
                    f"### Title\nMovie\n### {heading}\n{value}", "", ["movie"]
                )

    def event(self) -> dict[str, Any]:
        return {
            "issue": issue(),
            "comment": {
                "body": "@OvertureDB-bot approve",
                "user": {"login": "maintainer"},
                "created_at": "2026-09-23T10:00:01Z",
            },
        }

    def test_commands_are_exact_and_single_line(self) -> None:
        for text in (
            "hello",
            "@OvertureDB-bot rejected",
            "@OvertureDB-bot approve now",
            "@OvertureDB-bot reject\napprove",
            "@OvertureDB-bot approve\nmalicious",
        ):
            with self.subTest(text=text):
                self.assertIsNone(automation.parse_command(text))
        self.assertEqual(
            automation.parse_command("  @OvertureDB-bot approve\r\n"), ("approve", "")
        )
        self.assertEqual(
            automation.parse_command("@OvertureDB-bot reject wrong artwork"),
            ("reject", "wrong artwork"),
        )

    @patch.object(automation, "api")
    def test_permission_belongs_to_comment_author(self, api: MagicMock) -> None:
        api.side_effect = [{"permission": "write"}, issue()]
        event = self.event()
        with patch.dict("os.environ", {"GITHUB_ACTOR": "different-rerunner"}):
            self.assertEqual(automation.approved_issue(event, "owner/repo"), issue())
        self.assertEqual(
            api.call_args_list[0].args[0],
            "repos/owner/repo/collaborators/maintainer/permission",
        )

    @patch.object(automation, "api")
    def test_unprivileged_commands_never_load_or_modify_issue(
        self, api: MagicMock
    ) -> None:
        api.return_value = {"permission": "read"}
        with self.assertRaisesRegex(ValueError, "Write access"):
            automation.gate(self.event(), "owner/repo")
        self.assertEqual(api.call_count, 1)

    @patch.object(automation, "api")
    def test_edits_and_label_changes_require_fresh_approval(
        self, api: MagicMock
    ) -> None:
        for changes in (
            {"body": "new body"},
            {"title": "new title"},
            {"labels": [{"name": "contribution"}, {"name": "show"}]},
            {"updated_at": "2026-09-23T10:00:02Z"},
        ):
            with self.subTest(changes=changes):
                api.side_effect = [{"permission": "admin"}, issue(**changes)]
                with self.assertRaisesRegex(ValueError, "changed"):
                    automation.approved_issue(self.event(), "owner/repo")

    def test_invalid_issue_state_or_ambiguous_kind_is_rejected(self) -> None:
        invalid: list[dict[str, Any]] = [
            {"state": "closed"},
            {"pull_request": {}},
            {"labels": [{"name": "movie"}]},
            {"labels": issue()["labels"] + [{"name": "show"}]},
            {"labels": issue()["labels"] + [{"name": "rejected"}]},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                automation.contribution_kind(issue(**changes))
        with self.assertRaises(ValueError):
            parse_issue_form("", "[Movie]", ["movie", "show"])

    def test_youtube_links_cannot_match_an_attacker_host_or_partial_id(self) -> None:
        for url in (
            "https://notyoutube.com/watch?v=AB96CvvLZKc",
            "https://evil.test/youtube.com/watch?v=AB96CvvLZKc",
            "https://youtu.be/AB96CvvLZKc-extra",
            "https://youtube.com/watch?v=AB96CvvLZKc-extra",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                clean_youtube_id(url)


class PreviewTests(unittest.TestCase):
    @patch.object(automation, "gh")
    @patch.object(automation, "api")
    @patch.object(automation, "prepare")
    def test_spoofed_preview_marker_is_not_edited(
        self, prepare: MagicMock, api: MagicMock, gh: MagicMock
    ) -> None:
        prepare.return_value = {
            "body": "A preview",
            "labels": ["contribution", "movie"],
        }
        api.side_effect = [issue(), issue(), {}]
        gh.return_value = json.dumps(
            [[{"id": 99, "user": {"login": "attacker"}, "body": automation.MARKER}]]
        )
        automation.preview({"issue": issue()}, "owner/repo")
        self.assertEqual(
            api.call_args_list[-1].args[0], "repos/owner/repo/issues/12/comments"
        )
        self.assertFalse(any("PATCH" in call.args for call in gh.call_args_list))

    @patch.object(automation, "gh")
    @patch.object(automation, "api")
    @patch.object(automation, "prepare")
    def test_preview_does_not_publish_after_issue_changes(
        self, prepare: MagicMock, api: MagicMock, gh: MagicMock
    ) -> None:
        prepare.return_value = {"body": "A preview", "labels": ["movie"]}
        api.side_effect = [issue(), issue(body="edited")]
        automation.preview({"issue": issue()}, "owner/repo")
        gh.assert_not_called()

    def test_user_text_cannot_close_code_fence(self) -> None:
        result = automation.fenced("```\n@someone\n````")
        self.assertTrue(result.startswith("`````text\n"))
        self.assertTrue(result.endswith("\n`````"))

    @patch.object(automation, "api", return_value=[])
    @patch.object(automation, "gh")
    def test_disabled_protection_never_calls_merge(
        self, gh: MagicMock, _api: MagicMock
    ) -> None:
        with patch("sys.stdout", new=io.StringIO()):
            automation.enable_auto_merge(
                "owner/repo", "https://github.com/owner/repo/pull/1"
            )
        gh.assert_not_called()

    @patch.object(
        automation,
        "api",
        return_value=[
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "contribution-guard", "integration_id": 15368}
                    ]
                },
            }
        ],
    )
    @patch.object(automation, "gh", return_value="a" * 40)
    def test_merge_is_bound_to_reviewed_head(
        self, gh: MagicMock, _api: MagicMock
    ) -> None:
        automation.enable_auto_merge(
            "owner/repo", "https://github.com/owner/repo/pull/1"
        )
        self.assertEqual(
            gh.call_args_list[-1].args[-2:], ("--match-head-commit", "a" * 40)
        )


class ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "data/movies").mkdir(parents=True)
        self.archive = self.root / "export.zip"

    def archive_entries(self, *entries: dict[str, Any]) -> None:
        with ZipFile(self.archive, "w") as archive:
            for index, entry in enumerate(entries):
                archive.writestr(f"{index}.json", json.dumps(entry))

    def test_failed_import_writes_valid_subset_and_reports_skipped(self) -> None:
        self.archive_entries(movie(), movie(tmdb_id=2, year=False))
        result = import_bulk_export(overture_dir=self.root, archive_path=self.archive)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(len(list((self.root / "data").rglob("*.json"))), 1)

    def test_enriched_identity_is_indexed_for_later_records(self) -> None:
        path = self.root / "data/movies/tmdb-1.json"
        path.write_text(json.dumps(movie(poster_url=None)), encoding="utf-8")
        self.archive_entries(
            movie(imdb_id="tt1"),
            movie(
                tmdb_id=None,
                imdb_id="tt1",
                background_url="https://image.tmdb.org/background.jpg",
            ),
        )
        result = import_bulk_export(overture_dir=self.root, archive_path=self.archive)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["created"], 0)
        self.assertEqual(len(list((self.root / "data").rglob("*.json"))), 1)
        self.assertEqual(
            json.loads(path.read_text())["background_url"],
            "https://image.tmdb.org/background.jpg",
        )

    def test_existing_duplicate_identity_is_rejected_before_writing(self) -> None:
        for name, entry in (
            ("tmdb-1.json", movie()),
            ("imdb-tt1.json", movie(imdb_id="tt1")),
        ):
            (self.root / "data/movies" / name).write_text(
                json.dumps(entry), encoding="utf-8"
            )
        self.archive_entries(movie(tmdb_id=2))
        with self.assertRaisesRegex(ValueError, "Duplicate dataset identity"):
            import_bulk_export(overture_dir=self.root, archive_path=self.archive)
        self.assertFalse((self.root / "data/movies/tmdb-2.json").exists())

    def test_bulk_url_policy_does_not_depend_on_network_probes(self) -> None:
        self.archive_entries(movie(poster_url="https://127.0.0.1/private.jpg"))
        result = import_bulk_export(overture_dir=self.root, archive_path=self.archive)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(list((self.root / "data").rglob("*.json")), [])

    def test_empty_archive_and_missing_directory_are_errors(self) -> None:
        self.archive_entries()
        with self.assertRaises(ValueError):
            load_incoming_entries(archive_path=self.archive)
        with self.assertRaises(ValueError):
            load_incoming_entries(input_dir=self.root / "missing")

    def test_bulk_does_not_create_empty_entries_from_imported_theme_only(self) -> None:
        self.archive_entries(movie(poster_url=None, youtube_id_themerrdb="AB96CvvLZKc"))
        result = import_bulk_export(overture_dir=self.root, archive_path=self.archive)
        self.assertEqual(result["skipped"], 1)
        self.assertFalse(list((self.root / "data").rglob("*.json")))

    def test_zip_filenames_are_never_extracted(self) -> None:
        with ZipFile(self.archive, "w") as archive:
            archive.writestr("../../outside.json", json.dumps(movie()))
        import_bulk_export(overture_dir=self.root, archive_path=self.archive)
        self.assertFalse((self.root / "outside.json").exists())
        self.assertTrue((self.root / "data/movies/tmdb-1.json").exists())

    @patch.object(automation, "public_https_destination")
    @patch.object(automation, "build_opener")
    def test_download_enforces_actual_bytes_without_content_length(
        self, opener: MagicMock, destination: MagicMock
    ) -> None:
        response = MagicMock()
        response.read.side_effect = [b"a" * 6, b"b" * 6, b""]
        opener.return_value.open.return_value.__enter__.return_value = response
        with (
            patch.object(automation, "MAX_ARCHIVE_BYTES", 10),
            self.assertRaisesRegex(ValueError, "limit"),
        ):
            automation.download_archive(
                "https://github.com/user-attachments/assets/abc-123", self.archive
            )
        self.assertEqual(
            destination.call_args_list[-1].kwargs["allowed_hosts"], {"github.com"}
        )

    def test_attachment_redirect_rejects_untrusted_host_before_request(self) -> None:
        with self.assertRaises(ValueError):
            automation.AttachmentRedirectHandler().redirect_request(
                Request("https://github.com/user-attachments/assets/a"),
                io.BytesIO(),
                302,
                "Found",
                HTTPMessage(),
                "https://127.0.0.1/private",
            )

    @patch.object(automation, "build_opener")
    def test_non_attachment_or_multiple_links_never_download(
        self, opener: MagicMock
    ) -> None:
        for body in (
            "https://evil.test/archive.zip",
            "https://github.com/user-attachments/assets/a https://github.com/user-attachments/assets/b",
        ):
            with self.assertRaises(ValueError):
                automation.download_archive(body, self.archive)
        opener.assert_not_called()


class GuardTests(unittest.TestCase):
    def test_provenance_and_scope(self) -> None:
        pr: dict[str, Any] = {
            "head": {
                "repo": {"full_name": "owner/repo"},
                "ref": "contribution/issue-12",
            },
            "user": {"login": "overturedb[bot]"},
        }
        path = "data/movies/tmdb-1.json"
        self.assertEqual(validate_changes(pr, "owner/repo", [path], []), [path])
        for changed, deleted in (
            ([path, "README.md"], []),
            ([path], [path]),
            (["data/other.txt"], []),
        ):
            with self.assertRaises(ValueError):
                validate_changes(pr, "owner/repo", changed, deleted)
        bad = copy.deepcopy(pr)
        bad["user"]["login"] = "attacker"
        with self.assertRaises(ValueError):
            validate_changes(bad, "owner/repo", [path], [])
        bad = copy.deepcopy(pr)
        bad["head"]["repo"]["full_name"] = "attacker/repo"
        with self.assertRaises(ValueError):
            validate_changes(bad, "owner/repo", [path], [])
        self.assertEqual(validate_changes(bad, "owner/repo", ["README.md"], []), [])

    def test_missing_dataset_cannot_publish_empty_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            catalog.dataset(Path(directory))
