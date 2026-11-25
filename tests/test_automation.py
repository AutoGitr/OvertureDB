"""Security boundaries for public issue input and privileged automation."""

lazy import io
lazy import json
lazy from collections.abc import Callable
lazy from http.client import HTTPMessage
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import MagicMock, patch
lazy from urllib.request import Request
lazy from zipfile import ZipFile

lazy import pytest

lazy from scripts import automation
lazy from scripts.catalog import TransientError
lazy from scripts.contribution import (
    clean_youtube_id,
    parse_issue_form,
)
lazy from scripts.import_bulk_export import import_bulk_export, load_incoming_entries
lazy from tests.changes import apply_changes
lazy from tests.test_catalog import movie
lazy from tests.test_import_bulk_export import entry_count


@pytest.fixture(autouse=True)
def theme_problem(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Every contributed theme plays, unless a test says otherwise."""
    check = MagicMock(return_value=None)
    monkeypatch.setattr(automation, "theme_problem", check)
    return check


@pytest.fixture(autouse=True)
def theme_seconds(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Every contributed theme lasts a few minutes, unless a test says otherwise."""
    length = MagicMock(return_value=215)
    monkeypatch.setattr(automation, "theme_seconds", length)
    return length


#: The real check, which the autouse fixture below replaces in other tests.
IS_ADMIN = automation.is_admin


@pytest.fixture(autouse=True)
def admin(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Issues are opened by contributors, unless a test says an admin opened one."""
    check = MagicMock(return_value=False)
    monkeypatch.setattr(automation, "is_admin", check)
    return check


def issue(**changes: Any) -> dict[str, Any]:
    return {
        "number": 12,
        "user": {"login": "contributor"},
        "state": "open",
        "body": "body",
        "title": "Title",
        "labels": [{"name": "movie"}],
        "updated_at": "2026-09-23T10:00:00Z",
        **changes,
    }


def test_identifier_urls_require_real_provider_hosts(subtests: pytest.Subtests) -> None:
    for heading, value in (
        ("TMDB ID", "https://evil.test/themoviedb.org/movie/123"),
        ("TVDB ID", "https://notthetvdb.com/series/123"),
        ("IMDb ID", "unrelated-tt123-suffix"),
    ):
        with (
            subtests.test(heading=heading),
            pytest.raises(ValueError, match=r"ID must"),
        ):
            parse_issue_form(f"### Title\nMovie\n### {heading}\n{value}", ["movie"])


def approval_event() -> dict[str, Any]:
    return {
        "issue": issue(),
        "comment": {
            "body": "@OvertureDB-bot approve",
            "user": {"login": "maintainer"},
            "created_at": "2026-09-23T10:00:01Z",
        },
    }


def test_commands_are_exact_and_single_line(subtests: pytest.Subtests) -> None:
    for text in (
        "hello",
        "@OvertureDB-bot rejected",
        "@OvertureDB-bot approve now",
        "@OvertureDB-bot reject\napprove",
        "@OvertureDB-bot approve\nmalicious",
    ):
        with subtests.test(text=text):
            assert automation.parse_command(text) is None
    assert automation.parse_command("  @OvertureDB-bot approve\r\n") == (
        "approve",
        "",
    )
    assert automation.parse_command("@OvertureDB-bot reject wrong artwork") == (
        "reject",
        "wrong artwork",
    )


def test_invalid_issue_state_or_ambiguous_kind_is_rejected(
    subtests: pytest.Subtests,
) -> None:
    invalid: list[dict[str, Any]] = [
        {"state": "closed"},
        {"pull_request": {}},
        {"labels": []},
        {"labels": [{"name": "bug"}]},
        {"labels": issue()["labels"] + [{"name": "show"}]},
    ]
    for changes in invalid:
        with (
            subtests.test(changes=changes),
            pytest.raises(
                ValueError,
                match=r"Use one open movie, show, collection, bulk or preset",
            ),
        ):
            automation.contribution_kind(issue(**changes))
    with pytest.raises(
        ValueError,
        match=r"Issue must have exactly one movie, show or collection label\.",
    ):
        parse_issue_form("", ["movie", "show"])


def test_youtube_links_cannot_match_an_attacker_host_or_partial_id(
    subtests: pytest.Subtests,
) -> None:
    for url in (
        "https://notyoutube.com/watch?v=AB96CvvLZKc",
        "https://evil.test/youtube.com/watch?v=AB96CvvLZKc",
        "https://youtu.be/AB96CvvLZKc-extra",
        "https://youtube.com/watch?v=AB96CvvLZKc-extra",
    ):
        with (
            subtests.test(url=url),
            pytest.raises(ValueError, match=r"Invalid YouTube theme ID or URL:"),
        ):
            clean_youtube_id(url)


def test_user_text_cannot_close_code_fence() -> None:
    result = automation.fenced("```\n@someone\n````")
    assert result.startswith("`````text\n")
    assert result.endswith("\n`````")


@pytest.fixture
def import_stats() -> dict[str, Any]:
    return {
        "added": 2,
        "updated": 3,
        "skipped_error": 0,
        "skipped_unchanged": 4,
        "skipped_no_theme": 5,
        "skipped_invalid": 6,
        "lost_themes": ["Alien"],
    }


def comment(body: str) -> dict[str, Any]:
    return {"id": 1, "user": {"login": "github-actions[bot]"}, "body": body}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "data/movies").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def archive(root: Path) -> Path:
    return root / "export.zip"


@pytest.fixture
def publisher(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise approval orchestration; guard execution has integration tests."""

    def publish(
        repo: str,
        _root: Path,
        prepare: Callable[[Path], automation.publication.Commit | None],
        authorize: Callable[[], bool],
    ) -> str | None:
        plan = prepare(root)
        if plan is None or not authorize():
            return None
        return automation.github.commit_files(repo, "main", "base-sha", *plan)

    monkeypatch.setattr(automation.publication, "publish", publish)


def write_archive(path: Path, *entries: dict[str, Any]) -> None:
    with ZipFile(path, "w") as archive:
        for index, entry in enumerate(entries):
            archive.writestr(f"{index}.json", json.dumps(entry))


def test_failed_import_writes_valid_subset_and_reports_skipped(
    root: Path, archive: Path
) -> None:
    write_archive(archive, movie(), movie(tmdb_id=2, year=False))
    result = apply_changes(
        root, import_bulk_export(overture_dir=root, archive_path=archive)
    )
    assert len(result["errors"]) == 1
    assert len(list((root / "data").rglob("*.json"))) == 1


def test_malformed_bulk_records_are_skipped_without_losing_valid_records(
    subtests: pytest.Subtests,
    root: Path,
    archive: Path,
) -> None:
    records = {
        "valid.json": json.dumps(movie()).encode("utf-8"),
        "broken.json": b"{broken",
        "encoding.json": b"\xff",
    }
    input_dir = root / "input"
    input_dir.mkdir()
    with ZipFile(archive, "w") as zip_file:
        for name, content in records.items():
            zip_file.writestr(name, content)
            (input_dir / name).write_bytes(content)
    for archive_path, source_dir in ((archive, None), (None, input_dir)):
        with subtests.test(archive=archive_path, directory=source_dir):
            result = import_bulk_export(
                overture_dir=root,
                archive_path=archive_path,
                input_dir=source_dir,
            )
            assert entry_count(result, "new") == 1
            assert len(result["errors"]) == 2
            assert result["total_incoming"] == 3
            assert any("broken.json" in e for e in result["errors"])
            assert any("encoding.json" in e for e in result["errors"])
            assert not list((root / "data").rglob("*.json"))
    result = apply_changes(
        root, import_bulk_export(overture_dir=root, archive_path=archive)
    )
    assert entry_count(result, "new") == 1
    assert len(result["errors"]) == 2
    assert (root / "data/movies/tmdb-1.json").exists()


def test_enriched_identity_is_indexed_for_later_records(
    root: Path, archive: Path
) -> None:
    path = root / "data/movies/tmdb-1.json"
    path.write_text(json.dumps(movie(poster_url=None)))
    write_archive(
        archive,
        movie(imdb_id="tt1"),
        movie(
            tmdb_id=None,
            imdb_id="tt1",
            background_url="https://image.tmdb.org/t/p/original/background.jpg",
        ),
    )
    result = apply_changes(
        root, import_bulk_export(overture_dir=root, archive_path=archive)
    )
    assert result["errors"] == []
    assert entry_count(result, "new") == 0
    assert entry_count(result, "updated") == 1
    assert result["review_markdown"].count("#### A Movie") == 1
    assert len(list((root / "data").rglob("*.json"))) == 1
    assert (
        json.loads(path.read_text())["background_url"]
        == "https://image.tmdb.org/t/p/original/background.jpg"
    )


def test_existing_duplicate_identity_is_rejected_before_writing(
    root: Path, archive: Path
) -> None:
    for name, entry in (
        ("tmdb-1.json", movie()),
        ("imdb-tt1.json", movie(imdb_id="tt1")),
    ):
        (root / "data/movies" / name).write_text(json.dumps(entry))
    write_archive(archive, movie(tmdb_id=2))
    with pytest.raises(ValueError, match="Duplicate catalog identity"):
        import_bulk_export(overture_dir=root, archive_path=archive)
    assert not (root / "data/movies/tmdb-2.json").exists()


def test_bulk_url_policy_does_not_depend_on_network_probes(
    root: Path, archive: Path
) -> None:
    write_archive(archive, movie(poster_url="https://127.0.0.1/private.jpg"))
    result = apply_changes(
        root, import_bulk_export(overture_dir=root, archive_path=archive)
    )
    assert len(result["errors"]) == 1
    assert list((root / "data").rglob("*.json")) == []


def test_empty_archive_and_missing_directory_are_errors(
    root: Path, archive: Path
) -> None:
    write_archive(archive)
    with pytest.raises(ValueError, match=r"No JSON entries found"):
        load_incoming_entries(archive_path=archive)
    with pytest.raises(
        ValueError,
        match=r"Input directory does not exist",
    ):
        load_incoming_entries(input_dir=root / "missing")


def test_bulk_does_not_create_empty_entries_from_imported_theme_only(
    root: Path, archive: Path
) -> None:
    write_archive(archive, movie(poster_url=None, youtube_id_themerrdb="AB96CvvLZKc"))
    result = apply_changes(
        root, import_bulk_export(overture_dir=root, archive_path=archive)
    )
    assert len(result["errors"]) == 1
    assert not list((root / "data").rglob("*.json"))


def test_zip_filenames_are_never_extracted(root: Path, archive: Path) -> None:
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../../outside.json", json.dumps(movie()))
    apply_changes(root, import_bulk_export(overture_dir=root, archive_path=archive))
    assert not (root / "outside.json").exists()
    assert (root / "data/movies/tmdb-1.json").exists()


@patch.object(automation, "public_https_destination")
@patch.object(automation, "build_opener")
def test_download_enforces_actual_bytes_without_content_length(
    opener: MagicMock,
    destination: MagicMock,
    archive: Path,
) -> None:
    response = MagicMock()
    response.read.side_effect = [b"a" * 6, b"b" * 6, b""]
    opener.return_value.open.return_value.__enter__.return_value = response
    with (
        patch.object(automation, "MAX_ARCHIVE_BYTES", 10),
        pytest.raises(ValueError, match="limit"),
    ):
        automation.download_archive(
            "https://github.com/user-attachments/assets/abc-123", archive
        )
    assert destination.call_args_list[-1].kwargs["allowed_hosts"] == {"github.com"}


def test_attachment_redirect_rejects_untrusted_host_before_request() -> None:
    with pytest.raises(
        ValueError, match=r"URL must use public HTTPS on an allowed host"
    ):
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
    opener: MagicMock,
    archive: Path,
) -> None:
    for body in (
        "https://evil.test/archive.zip",
        "https://github.com/user-attachments/assets/a https://github.com/user-attachments/assets/b",
    ):
        with pytest.raises(
            ValueError, match=r"Attach exactly one GitHub\-hosted selections ZIP\."
        ):
            automation.download_archive(body, archive)
    opener.assert_not_called()


@patch.object(automation, "check_art_url")
def test_only_submitted_artwork_must_follow_the_one_percent_rule(
    probe: MagicMock,
) -> None:
    old = movie()
    new = movie(background_url="https://image.tmdb.org/t/p/original/new.jpg")
    sizes = {old["poster_url"]: (1000, 1000), new["background_url"]: (1920, 1080)}
    probe.side_effect = sizes.get
    assert automation.check_submission(new, old) == []
    assert probe.call_count == 2
    with pytest.raises(ValueError, match="1% rule"):
        automation.check_submission(new, None)


@patch.object(automation, "check_art_url")
def test_submitted_artwork_below_the_recommended_resolution_is_a_warning(
    probe: MagicMock,
) -> None:
    old = movie()
    new = movie(background_url="https://image.tmdb.org/t/p/original/new.jpg")
    sizes = {old["poster_url"]: (800, 1200), new["background_url"]: (960, 540)}
    probe.side_effect = sizes.get
    assert automation.check_submission(new, old) == [
        (
            f"The background {new['background_url']} is 960x540 is below the "
            "recommended 1280x720."
        )
    ]


@patch.object(automation, "check_art_url", return_value=None)
def test_unmeasured_artwork_is_not_rejected(probe: MagicMock) -> None:
    automation.check_submission(movie(), None)


@patch.object(automation, "check_art_url", return_value=None)
def test_a_submitted_theme_must_play_on_youtube(
    probe: MagicMock, theme_problem: MagicMock
) -> None:
    old = movie(youtube_id_overturedb="AB96CvvLZKc")
    automation.check_submission(old, old)
    theme_problem.assert_not_called()
    new = movie(youtube_id_overturedb="4xdyx5NVUhI")
    theme_problem.return_value = "removed"
    with pytest.raises(ValueError, match="4xdyx5NVUhI is removed on YouTube"):
        automation.check_submission(new, old)
    theme_problem.side_effect = TransientError("HTTP 500")
    with pytest.raises(ValueError, match="Edit the issue to check again"):
        automation.check_submission(new, None)


@patch.object(automation, "check_art_url", return_value=None)
def test_a_submitted_theme_lasts_20_seconds_to_10_minutes(
    probe: MagicMock, theme_seconds: MagicMock
) -> None:
    new = movie(youtube_id_overturedb="4xdyx5NVUhI")
    for seconds in (20, 600):
        theme_seconds.return_value = seconds
        automation.check_submission(new, None)
    for seconds in (19, 601):
        theme_seconds.return_value = seconds
        with pytest.raises(ValueError, match=f"is {seconds} seconds long"):
            automation.check_submission(new, None)
    theme_seconds.side_effect = TransientError("no length")
    with pytest.raises(ValueError, match="Edit the issue to check again"):
        automation.check_submission(new, None)


@patch.object(automation, "check_art_url", return_value=None)
def test_evaluate_single_and_non_overlapping_changes_preserve_fingerprint(
    probe: MagicMock, root: Path
) -> None:
    path = root / "data/movies/imdb-tt1.json"
    path.write_text(json.dumps(movie(tmdb_id=None, imdb_id="tt1")))
    update_issue = issue(
        title="[Movie]: A Movie (1979)",
        body=(
            "### Title\nA Movie\n### Year\n1979\n### IMDb ID\ntt1\n### TMDB ID\n1\n"
            "### Background URL\nhttps://image.tmdb.org/t/p/original/bg.jpg\n"
            "### Reason for modification\nAdd TMDB ID and background"
        ),
    )
    plan1 = automation.evaluate_issue("AutoGitr/OvertureDB", update_issue, root)
    assert plan1.headline == "Update movie: A Movie (1979) (#12)"
    assert plan1.commit_body == "Closes #12"
    assert plan1.is_modification is True
    assert list(plan1.additions) == ["data/movies/tmdb-1.json"]
    assert plan1.deletions == ["data/movies/imdb-tt1.json"]
    assert "**Reason:** Add TMDB ID and background" in plan1.preview_body

    # Non-overlapping concurrent update on main (e.g. ThemerrDB theme backfill)
    # does NOT invalidate the reviewed field fingerprint!
    path.write_text(
        json.dumps(
            movie(tmdb_id=None, imdb_id="tt1", youtube_id_themerrdb="AB96CvvLZKc")
        )
    )
    plan2 = automation.evaluate_issue("AutoGitr/OvertureDB", update_issue, root)
    assert plan2.fingerprint == plan1.fingerprint
    assert "AB96CvvLZKc" in str(plan2.additions["data/movies/tmdb-1.json"])

    # Overlapping concurrent change on main (same background_url field changed)
    # DOES change the fingerprint!
    path.write_text(
        json.dumps(
            movie(
                tmdb_id=None,
                imdb_id="tt1",
                background_url="https://image.tmdb.org/t/p/original/other.jpg",
            )
        )
    )
    plan3 = automation.evaluate_issue("AutoGitr/OvertureDB", update_issue, root)
    assert plan3.fingerprint != plan1.fingerprint


def test_evaluate_single_remove_entry(root: Path) -> None:
    path = root / "data/movies/tmdb-1.json"
    path.write_text(
        json.dumps(movie(poster_url=None, youtube_id_overturedb="AB96CvvLZKc"))
    )
    remove_issue = issue(
        title="[Movie]: A Movie (2026)",
        body=(
            "### Title\nA Movie\n### Year\n2026\n### TMDB ID\n1\n"
            "### YouTube theme video ID\nAB96CvvLZKc\n"
            "### Removal\n- [x] Remove the fields provided in this issue\n"
            "### Reason for modification\nWrong theme"
        ),
    )
    plan = automation.evaluate_issue("AutoGitr/OvertureDB", remove_issue, root)
    assert plan.headline == "Remove movie: A Movie (2026) (#12)"
    assert plan.additions == {}
    assert plan.deletions == ["data/movies/tmdb-1.json"]


@patch.object(automation, "download_archive")
def test_evaluate_bulk_success_and_validation_errors(
    download: MagicMock, root: Path
) -> None:
    bulk_issue = issue(
        labels=[{"name": "bulk"}],
        body="https://github.com/user-attachments/assets/abc",
    )

    def write_valid(_body: str, target: Path) -> None:
        write_archive(target, movie())

    def write_invalid(_body: str, target: Path) -> None:
        write_archive(target, movie(tmdb_id=2, year=False))

    download.side_effect = write_valid
    plan = automation.evaluate_issue("AutoGitr/OvertureDB", bulk_issue, root)
    assert plan.kind == "bulk"
    assert plan.headline == "Bulk contribution: 1 added, 0 updated (#12)"
    assert "data/movies/tmdb-1.json" in plan.additions

    # If all entries already exist, NoChangesError is raised
    (root / "data/movies/tmdb-1.json").write_text(json.dumps(movie()))
    with pytest.raises(automation.NoChangesError):
        automation.evaluate_issue("AutoGitr/OvertureDB", bulk_issue, root)

    # Malformed record in bulk archive raises ValueError
    download.side_effect = write_invalid
    with pytest.raises(ValueError, match="Bulk validation failed"):
        automation.evaluate_issue("AutoGitr/OvertureDB", bulk_issue, root)


def test_format_bulk_errors_and_conflict_message() -> None:
    errors = [
        "data/movies/tmdb-1.json: Conflicting tvdb_id: existing=10, incoming=20",
        "plain error without separator",
    ]
    formatted = automation.format_bulk_errors(errors)
    assert "Bulk validation failed with 2 errors:" in formatted
    assert (
        "- `data/movies/tmdb-1.json`: Conflicting `tvdb_id`: "
        "existing=`10`, incoming=`20`"
    ) in formatted
    assert "- plain error without separator" in formatted

    many = [f"file-{i}.json: error" for i in range(60)]
    formatted_many = automation.format_bulk_errors(many)
    assert "Bulk validation failed with 60 errors:" in formatted_many
    assert "... and 10 more errors" in formatted_many


def test_format_bulk_summary_table() -> None:
    res: dict[str, Any] = {
        "overwrite": False,
        "total_incoming": 2920,
        "entries": {
            "new": {"movie": 900, "show": 200, "collection": 72},
            "updated": {"movie": 1000, "show": 300, "collection": 68},
            "overwritten": {},
            "unchanged": {"movie": 300, "show": 50, "collection": 30},
        },
        "changes": {
            "identifiers": {"filled": 1368},
            "posters": {"added": 1172, "filled": 1200},
            "themes": {"added": 250, "filled": 50},
        },
    }
    table = automation.format_bulk_summary(res)
    assert table.startswith("This contribution adds new entries and fills only")
    assert "| Entries | Movies | Shows | Collections | Total |" in table
    assert "| **New entries** | 900 | 200 | 72 | 1,172 |" in table
    assert "| **Filled gaps** | 1,000 | 300 | 68 | 1,368 |" in table
    assert "| **Overwritten** | 0 | 0 | 0 | 0 |" in table
    assert "| **Unchanged** | 300 | 50 | 30 | 380 |" in table
    assert "| **Total in export** | 2,200 | 550 | 170 | 2,920 |" in table
    assert "| Changes | In new entries | Filled | Replaced | Total |" in table
    assert "| Identifiers | 0 | 1,368 | 0 | 1,368 |" in table
    assert "| Posters | 1,172 | 1,200 | 0 | 2,372 |" in table
    assert "| **Total** | 1,422 | 2,618 | 0 | 4,040 |" in table
    assert "Backgrounds" not in table

    admin = automation.format_bulk_summary({**res, "overwrite": True})
    assert admin.startswith("> [!IMPORTANT]\n> Opened by an admin")


@patch.object(automation, "download_archive")
def test_an_admins_bulk_contribution_overwrites_and_says_so(
    download: MagicMock, admin: MagicMock, root: Path
) -> None:
    (root / "data/movies/tmdb-1.json").write_text(json.dumps(movie()))
    replacement = "https://image.tmdb.org/t/p/original/replacement.jpg"

    def write(_body: str, target: Path) -> None:
        write_archive(target, movie(poster_url=replacement))

    download.side_effect = write
    bulk = issue(
        labels=[{"name": "bulk"}], body="https://github.com/user-attachments/assets/abc"
    )

    with pytest.raises(automation.NoChangesError):
        automation.evaluate_issue("AutoGitr/OvertureDB", bulk, root)
    admin.return_value = True
    plan = automation.evaluate_issue("AutoGitr/OvertureDB", bulk, root)

    admin.assert_called_with("AutoGitr/OvertureDB", "contributor")
    assert plan.headline == "Bulk contribution: 0 added, 0 updated, 1 overwritten (#12)"
    assert plan.is_modification
    assert "<summary><b>Overwritten (1)</b></summary>" in plan.preview_body
    assert f"[New](<{replacement}>)" in plan.preview_body
    assert json.loads(plan.additions["data/movies/tmdb-1.json"])["poster_url"] == (
        replacement
    )


@patch.object(automation.github, "api")
def test_only_the_admin_permission_is_admin(api: MagicMock) -> None:
    for permission, expected in (("admin", True), ("maintain", False)):
        api.return_value = {"permission": permission}
        assert IS_ADMIN("AutoGitr/OvertureDB", "someone") is expected
    api.assert_called_with("repos/AutoGitr/OvertureDB/collaborators/someone/permission")


@patch.object(automation, "check_art_url", return_value=None)
@patch.object(automation.github, "pages", return_value=[])
@patch.object(automation.github, "api")
def test_preview_issue_handles_ready_satisfied_and_error_states(
    api: MagicMock,
    pages: MagicMock,
    probe: MagicMock,
    root: Path,
) -> None:
    valid_issue = issue(
        labels=[{"name": "movie"}, {"name": "edit"}],
        body=(
            f"### Title\nA Movie\n### Year\n2026\n### TMDB ID\n1\n"
            f"### Poster URL\n{movie()['poster_url']}"
        ),
    )
    automation.preview_issue("AutoGitr/OvertureDB", valid_issue, root)
    # Since this is a new entry (not a modification), the 'edit' label is removed
    assert any(
        call.args == ("repos/AutoGitr/OvertureDB/issues/12/labels/edit",)
        and call.kwargs == {"method": "DELETE"}
        for call in api.call_args_list
    )
    posted_body = api.call_args.args[1]["body"]
    assert "Ready for review" not in posted_body
    assert "<!-- fingerprint: " in posted_body

    # Already satisfied
    (root / "data/movies/tmdb-1.json").write_text(json.dumps(movie()))
    automation.preview_issue("AutoGitr/OvertureDB", valid_issue, root)
    assert "**Already satisfied**" in api.call_args.args[1]["body"]

    # Invalid issue form
    bad_issue = issue(body="### Title\nOnly title")
    automation.preview_issue("AutoGitr/OvertureDB", bad_issue, root)
    assert "**Needs attention**" in api.call_args.args[1]["body"]


@pytest.mark.usefixtures("publisher")
@patch.object(automation, "approval_is_current", return_value=True)
@patch.object(automation, "check_art_url", return_value=None)
@patch.object(automation.github, "commit_files", return_value="deadbeef")
@patch.object(automation.github, "git", return_value="base-sha")
@patch.object(automation.github, "pages")
@patch.object(automation.github, "api")
def test_approve_and_reject_issue(
    api: MagicMock,
    pages: MagicMock,
    git: MagicMock,
    commit_files: MagicMock,
    probe: MagicMock,
    current: MagicMock,
    root: Path,
) -> None:
    valid_issue = issue(
        body=(
            f"### Title\nA Movie\n### Year\n2026\n### TMDB ID\n1\n"
            f"### Poster URL\n{movie()['poster_url']}"
        ),
    )
    plan = automation.evaluate_issue("AutoGitr/OvertureDB", valid_issue, root)
    # 1. Stale / missing preview -> refreshes preview and does not commit
    pages.return_value = []
    automation.approve_issue(
        "AutoGitr/OvertureDB",
        valid_issue,
        {"created_at": "2026-09-23T10:05:00Z"},
        root,
    )
    commit_files.assert_not_called()
    assert "changed since the previous preview" in api.call_args.args[1]["body"]

    # 2. Matching preview -> commits directly and closes issue
    preview_body = (
        f"{automation.MARKER}\n"
        f"<!-- fingerprint: {plan.fingerprint} -->\n"
        "**Ready for review**"
    )
    pages.return_value = [
        {
            "id": 99,
            "user": {"login": automation.github.BOT_LOGIN},
            "updated_at": "2026-09-23T10:00:00Z",
            "body": preview_body,
        }
    ]
    automation.approve_issue(
        "AutoGitr/OvertureDB",
        valid_issue,
        {"created_at": "2026-09-23T10:05:00Z"},
        root,
    )
    commit_files.assert_called_once()
    assert api.call_args.args == (
        "repos/AutoGitr/OvertureDB/issues/12",
        {"state": "closed", "state_reason": "completed"},
    )

    # 3. Already satisfied on approve -> closes issue as completed without committing
    commit_files.reset_mock()
    (root / "data/movies/tmdb-1.json").write_text(json.dumps(movie()))
    automation.approve_issue(
        "AutoGitr/OvertureDB",
        valid_issue,
        {"created_at": "2026-09-23T10:05:00Z"},
        root,
    )
    commit_files.assert_not_called()
    assert api.call_args.args == (
        "repos/AutoGitr/OvertureDB/issues/12",
        {"state": "closed", "state_reason": "completed"},
    )

    # 4. Reject issue posts reason and closes as not_planned
    automation.reject_issue("AutoGitr/OvertureDB", valid_issue, "wrong aspect ratio")
    assert api.call_args.args == (
        "repos/AutoGitr/OvertureDB/issues/12",
        {"state": "closed", "state_reason": "not_planned"},
    )


@patch.object(automation, "approve_issue")
@patch.object(automation, "reject_issue")
@patch.object(automation, "preview_issue")
@patch.object(automation.github, "api")
def test_main_dispatches_events_and_enforces_permissions(
    api: MagicMock,
    preview: MagicMock,
    reject: MagicMock,
    approve: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_path = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_REPOSITORY", "AutoGitr/OvertureDB")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    # Rejects non-main ref
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    with pytest.raises(ValueError, match="must run on main"):
        automation.main()

    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")

    # workflow_dispatch with issue input
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("INPUT_ISSUE", "12")
    event_path.write_text("{}")
    api.return_value = issue()
    automation.main()
    assert preview.call_count == 1

    # issues event
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues")
    event_path.write_text(json.dumps({"issue": {"number": 12}}))
    automation.main()
    assert preview.call_count == 2

    # issue_comment event: unauthorized user ignored, authorized user runs commands
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    event_path.write_text(json.dumps(approval_event()))
    api.side_effect = [issue(), {"permission": "read"}]
    automation.main()
    approve.assert_not_called()

    api.side_effect = [issue(), {"permission": "write"}]
    automation.main()
    approve.assert_called_once()

    event_path.write_text(
        json.dumps(
            {
                "issue": issue(),
                "comment": {
                    "body": "@OvertureDB-bot reject duplicate",
                    "user": {"login": "maintainer"},
                    "created_at": "2026-09-23T10:00:01Z",
                },
            }
        )
    )
    api.side_effect = [issue(), {"permission": "admin"}]
    automation.main()
    reject.assert_called_once_with("AutoGitr/OvertureDB", issue(), "duplicate")


@patch.object(automation.github, "api")
def test_a_form_issue_without_its_kind_label_gets_it(api: MagicMock) -> None:
    api.return_value = [{"name": "collection"}]
    unlabeled = issue(title="[Collection]: Alien Collection", labels=[])
    labeled = automation.with_kind_label("AutoGitr/OvertureDB", unlabeled)
    assert labeled["labels"] == [{"name": "collection"}]
    api.assert_called_once_with(
        "repos/AutoGitr/OvertureDB/issues/12/labels", {"labels": ["collection"]}
    )

    api.reset_mock()
    for other in (issue(), issue(title="Catalog health", labels=[])):
        assert automation.with_kind_label("AutoGitr/OvertureDB", other) is other
    api.assert_not_called()


@patch.object(automation, "download_archive")
def test_bulk_approval_fingerprint_changes_when_new_writes_become_possible(
    download: MagicMock, root: Path
) -> None:
    def download_export(_body: str, target: Path) -> None:
        # Copy fixed bytes: archive timestamps must not affect this test.
        target.write_bytes(archive.read_bytes())

    archive = root / "export.zip"
    write_archive(archive, movie(), movie(tmdb_id=2))
    download.side_effect = download_export
    path = root / "data/movies/tmdb-1.json"
    path.write_text(json.dumps(movie()))
    bulk = issue(labels=[{"name": "bulk"}])
    before = automation.evaluate_issue("AutoGitr/OvertureDB", bulk, root)
    path.unlink()
    after = automation.evaluate_issue("AutoGitr/OvertureDB", bulk, root)
    assert len(before.additions) == 1
    assert len(after.additions) == 2
    assert before.fingerprint != after.fingerprint


@pytest.mark.parametrize(
    "change",
    [
        {"state": "closed"},
        {"body": "new body"},
        {"title": "new title"},
        {"labels": [{"name": "bulk"}]},
    ],
)
@patch.object(automation.github, "api")
def test_approval_stops_when_issue_changes(
    api: MagicMock, change: dict[str, Any]
) -> None:
    api.return_value = issue(**change)
    assert not automation.approval_is_current("owner/repo", issue(), {})
    assert api.call_count == 1


@pytest.mark.parametrize(
    ("change", "permission", "expected"),
    [
        ({}, "write", True),
        ({}, "read", False),
        ({"body": "withdrawn"}, "write", False),
        ({"updated_at": "later"}, "write", False),
        ({"user": {"login": "other"}}, "write", False),
    ],
)
@patch.object(automation.github, "api")
def test_live_approval_must_be_unchanged_and_authorized(
    api: MagicMock, change: dict[str, Any], permission: str, expected: bool
) -> None:
    approval = {**approval_event()["comment"], "id": 7, "updated_at": "original"}
    # Status labels must not revoke an otherwise valid approval.
    live_issue = issue(labels=[{"name": "movie"}, {"name": "edit"}])
    api.side_effect = [live_issue, {**approval, **change}, {"permission": permission}]
    assert automation.approval_is_current("owner/repo", issue(), approval) is expected


@pytest.mark.usefixtures("publisher")
@patch.object(automation, "evaluate_issue")
@patch.object(automation, "find_preview_comment")
@patch.object(automation, "approval_is_current", return_value=True)
@patch.object(automation, "upsert_comment")
@patch.object(automation.github, "git", return_value="head")
@patch.object(automation.github, "commit_files", side_effect=RuntimeError("head moved"))
@patch.object(automation.github, "api")
def test_failed_commit_keeps_issue_open_and_explains_recovery(
    api: MagicMock,
    commit: MagicMock,
    git: MagicMock,
    upsert: MagicMock,
    current: MagicMock,
    preview: MagicMock,
    evaluate: MagicMock,
    root: Path,
) -> None:
    fingerprint = "a" * 64
    evaluate.return_value = automation.Plan(
        "movie", "title", "body", "preview", fingerprint, {}, []
    )
    preview.return_value = {
        "body": f"<!-- fingerprint: {fingerprint} -->",
        "updated_at": "2026-09-23T10:00:00Z",
    }
    approval = {"created_at": "2026-09-23T10:00:01Z"}
    with pytest.raises(RuntimeError, match="head moved"):
        automation.approve_issue("owner/repo", issue(), approval, root)
    assert "Checks or commit need attention" in upsert.call_args.args[2]
    api.assert_not_called()
    commit.assert_called_once()

    commit.reset_mock()
    current.return_value = False
    automation.approve_issue("owner/repo", issue(), approval, root)
    commit.assert_not_called()


@patch.object(automation, "_evaluate_single")
def test_oversized_preview_is_rejected_before_posting(
    evaluate: MagicMock, root: Path
) -> None:
    evaluate.return_value = automation.Plan(
        "movie", "title", "body", "x" * 60_000, "a" * 64, {}, []
    )
    with pytest.raises(ValueError, match="Split the contribution"):
        automation.evaluate_issue("AutoGitr/OvertureDB", issue(), root)


@patch("scripts.import_bulk_export.ZipFile.read", side_effect=RuntimeError("encrypted"))
def test_encrypted_archive_has_actionable_error(read: MagicMock, archive: Path) -> None:
    write_archive(archive, movie())
    with pytest.raises(ValueError, match="unencrypted ZIP"):
        load_incoming_entries(archive_path=archive)


def test_bulk_preview_excludes_unchanged_records(root: Path, archive: Path) -> None:
    (root / "data/movies/tmdb-1.json").write_text(json.dumps(movie()))
    write_archive(archive, *([movie()] * 500), movie(tmdb_id=2))
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert result["total_incoming"] == 501
    assert entry_count(result, "unchanged") == 500
    assert entry_count(result, "new") == 1
    assert len(result["additions"]) == 1
    assert result["review_markdown"].count("#### A Movie") == 1


def test_bulk_preview_consolidates_new_entry_backfills(
    root: Path, archive: Path
) -> None:
    write_archive(
        archive,
        movie(),
        movie(background_url="https://image.tmdb.org/t/p/original/bg.jpg"),
    )
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert entry_count(result, "new") == 1
    assert entry_count(result, "updated") == 0
    assert result["review_markdown"].count("#### A Movie") == 1
    assert "**Poster:**" in result["review_markdown"]
    assert "**Background:**" in result["review_markdown"]


@patch("scripts.import_bulk_export.format_review_markdown")
def test_bulk_validation_errors_take_priority_over_review_limit(
    format_review: MagicMock, root: Path, archive: Path
) -> None:
    format_review.side_effect = ValueError("too many changes")
    (root / "data/movies/tmdb-1.json").write_text(json.dumps(movie(tvdb_id=1)))
    write_archive(archive, movie(tvdb_id=2), movie(tmdb_id=2))
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert "Conflicting tvdb_id" in result["errors"][0]
    assert result["review_markdown"] == ""
    format_review.assert_not_called()
    assert not (root / "data/movies/tmdb-2.json").exists()


def test_bulk_ignores_exported_imported_themes_during_validation(
    root: Path, archive: Path
) -> None:
    write_archive(
        archive,
        movie(youtube_id_overturedb="AB96CvvLZKc", youtube_id_themerrdb="AB96CvvLZKc"),
    )
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert result["errors"] == []
    created = json.loads(result["additions"]["data/movies/tmdb-1.json"])
    assert created["youtube_id_overturedb"] == "AB96CvvLZKc"
    assert created["youtube_id_themerrdb"] is None

    # Duplicate checking uses the authoritative imported theme on main.
    (root / "data/movies/tmdb-1.json").write_text(
        json.dumps(movie(youtube_id_themerrdb="AB96CvvLZKc"))
    )
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert result["additions"] == {}
    assert entry_count(result, "unchanged") == 1
