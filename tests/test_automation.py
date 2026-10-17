"""Security boundaries for public issue input and privileged automation."""

lazy import io
lazy import json
lazy from http.client import HTTPMessage
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import MagicMock, patch
lazy from urllib.request import Request
lazy from zipfile import ZipFile

lazy import pytest

lazy from scripts import automation
lazy from scripts.contribution import (
    clean_youtube_id,
    parse_issue_form,
)
lazy from scripts.import_bulk_export import import_bulk_export, load_incoming_entries
lazy from tests.test_catalog import movie


def issue(**changes: Any) -> dict[str, Any]:
    return {
        "number": 12,
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
        with subtests.test(heading=heading), pytest.raises(ValueError):
            parse_issue_form(f"### Title\nMovie\n### {heading}\n{value}", "", ["movie"])


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
        with subtests.test(changes=changes), pytest.raises(ValueError):
            automation.contribution_kind(issue(**changes))
    with pytest.raises(ValueError):
        parse_issue_form("", "[Movie]", ["movie", "show"])


def test_youtube_links_cannot_match_an_attacker_host_or_partial_id(
    subtests: pytest.Subtests,
) -> None:
    for url in (
        "https://notyoutube.com/watch?v=AB96CvvLZKc",
        "https://evil.test/youtube.com/watch?v=AB96CvvLZKc",
        "https://youtu.be/AB96CvvLZKc-extra",
        "https://youtube.com/watch?v=AB96CvvLZKc-extra",
    ):
        with subtests.test(url=url), pytest.raises(ValueError):
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


def write_archive(path: Path, *entries: dict[str, Any]) -> None:
    with ZipFile(path, "w") as archive:
        for index, entry in enumerate(entries):
            archive.writestr(f"{index}.json", json.dumps(entry))


def test_failed_import_writes_valid_subset_and_reports_skipped(
    root: Path, archive: Path
) -> None:
    write_archive(archive, movie(), movie(tmdb_id=2, year=False))
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert result["skipped"] == 1
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
    for source in ({"archive_path": archive}, {"input_dir": input_dir}):
        with subtests.test(source=source):
            result = import_bulk_export(overture_dir=root, dry_run=True, **source)
            assert result["created"] == 1
            assert result["skipped"] == 2
            assert result["total_incoming"] == 3
            assert any("broken.json" in e for e in result["errors"])
            assert any("encoding.json" in e for e in result["errors"])
            assert not list((root / "data").rglob("*.json"))
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert result["created"] == 1
    assert result["skipped"] == 2
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
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert result["errors"] == []
    assert result["created"] == 0
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
    with pytest.raises(ValueError, match="Duplicate dataset identity"):
        import_bulk_export(overture_dir=root, archive_path=archive)
    assert not (root / "data/movies/tmdb-2.json").exists()


def test_bulk_url_policy_does_not_depend_on_network_probes(
    root: Path, archive: Path
) -> None:
    write_archive(archive, movie(poster_url="https://127.0.0.1/private.jpg"))
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert result["skipped"] == 1
    assert list((root / "data").rglob("*.json")) == []


def test_empty_archive_and_missing_directory_are_errors(
    root: Path, archive: Path
) -> None:
    write_archive(archive)
    with pytest.raises(ValueError):
        load_incoming_entries(archive_path=archive)
    with pytest.raises(ValueError):
        load_incoming_entries(input_dir=root / "missing")


def test_bulk_does_not_create_empty_entries_from_imported_theme_only(
    root: Path, archive: Path
) -> None:
    write_archive(archive, movie(poster_url=None, youtube_id_themerrdb="AB96CvvLZKc"))
    result = import_bulk_export(overture_dir=root, archive_path=archive)
    assert result["skipped"] == 1
    assert not list((root / "data").rglob("*.json"))


def test_zip_filenames_are_never_extracted(root: Path, archive: Path) -> None:
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../../outside.json", json.dumps(movie()))
    import_bulk_export(overture_dir=root, archive_path=archive)
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
    with pytest.raises(ValueError):
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
        with pytest.raises(ValueError):
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
    automation.check_artwork(new, old)
    assert probe.call_count == 2
    with pytest.raises(ValueError, match="1% rule"):
        automation.check_artwork(new, None)


@patch.object(automation, "check_art_url", return_value=None)
def test_unmeasured_artwork_is_not_rejected(_probe: MagicMock) -> None:
    automation.check_artwork(movie(), None)
