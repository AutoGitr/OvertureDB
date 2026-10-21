"""Unit tests for the ThemerrDB import script."""

lazy import json
lazy from dataclasses import dataclass
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import MagicMock, patch

lazy import pytest

lazy from schema.contract import validate_entry
lazy from scripts import import_themerrdb as importer
lazy from scripts.catalog import EntryIndex
lazy from tests.test_catalog import movie


def test_extract_youtube_id(subtests: pytest.Subtests) -> None:
    valid_cases = [
        ("4xdyx5NVUhI", "4xdyx5NVUhI"),
        ("https://www.youtube.com/watch?v=4xdyx5NVUhI", "4xdyx5NVUhI"),
        ("https://www.youtube.com/watch?v=4xdyx5NVUhI&t=10s", "4xdyx5NVUhI"),
        ("https://youtube.com/watch?v=4xdyx5NVUhI", "4xdyx5NVUhI"),
        ("https://m.youtube.com/watch?v=4xdyx5NVUhI", "4xdyx5NVUhI"),
        ("https://youtu.be/4xdyx5NVUhI", "4xdyx5NVUhI"),
        ("https://www.youtube.com/embed/4xdyx5NVUhI", "4xdyx5NVUhI"),
        ("https://www.youtube.com/v/4xdyx5NVUhI", "4xdyx5NVUhI"),
    ]
    for input_val, expected in valid_cases:
        with subtests.test(input_val=input_val):
            assert importer.extract_youtube_id(input_val) == expected

    invalid_cases = [
        None,
        "",
        "   ",
        "short",
        "too_long_youtube_id_12345",
        "https://vimeo.com/123456",
        "https://youtube.com/watch",
        "https://youtube.com/watch?v=short",
        "https://youtube.com/watch?v=4xdyx5NVUhI%0A",
        "https://[malformed/watch?v=4xdyx5NVUhI",
    ]
    for input_val in invalid_cases:
        with subtests.test(input_val=input_val):
            assert importer.extract_youtube_id(input_val) is None


def test_parse_year() -> None:
    assert importer.parse_year("2014-10-10") == 2014
    assert importer.parse_year("1995") == 1995
    assert importer.parse_year(None) is None
    assert importer.parse_year("") is None
    assert importer.parse_year("0999-01-01") is None
    assert importer.parse_year("not-a-date") is None


def test_process_themerr_item_updates_existing_entry(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    movies_dir = data_dir / "movies"
    movies_dir.mkdir(parents=True)

    existing_file = movies_dir / "tmdb-252178.json"
    existing_data = {
        "media_type": "movie",
        "title": "'71",
        "year": 2014,
        "tmdb_id": 252178,
        "tvdb_id": 4092,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/curated.jpg",
        "background_url": "https://image.tmdb.org/t/p/original/bg.jpg",
        "youtube_id_overturedb": "original_yt",
        "youtube_id_themerrdb": None,
    }
    existing_file.write_text(json.dumps(existing_data))

    index = EntryIndex.load(data_dir.parent)

    themerr_record = {
        "id": 252178,
        "imdb_id": "tt2614684",
        "title": "'71",
        "release_date": "2014-10-10",
        "youtube_theme_url": "https://www.youtube.com/watch?v=themerr_sec",
        "poster_path": "/themerr_poster.jpg",
    }

    status = importer.process_themerr_item(
        themerr_record,
        "movie",
        index,
        data_dir,
    )

    assert status == "updated"

    assert json.loads(existing_file.read_text()) == existing_data
    updated_data = index.entries[existing_file]
    assert updated_data["youtube_id_overturedb"] == "original_yt"
    assert updated_data["youtube_id_themerrdb"] == "themerr_sec"
    # Must NOT touch imdb_id or poster_url
    assert updated_data["imdb_id"] is None
    assert (
        updated_data["poster_url"] == "https://image.tmdb.org/t/p/original/curated.jpg"
    )
    validate_entry(updated_data)


def test_process_themerr_item_adds_new_movie(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    index = EntryIndex.load(data_dir.parent)

    themerr_record = {
        "id": 99999,
        "imdb_id": "tt9999999",
        "title": "New Film",
        "release_date": "2023-05-12",
        "youtube_theme_url": "https://youtu.be/newfilmthem",
        "poster_path": "/new_poster.jpg",
        "backdrop_path": "/new_bg.jpg",
    }

    status = importer.process_themerr_item(
        themerr_record,
        "movie",
        index,
        data_dir,
    )

    assert status == "added"

    target_file = data_dir / "movies" / "tmdb-99999.json"
    assert not target_file.exists()

    saved = index.entries[target_file]
    assert saved["media_type"] == "movie"
    assert saved["title"] == "New Film"
    assert saved["year"] == 2023
    assert saved["tmdb_id"] == 99999
    assert saved["youtube_id_overturedb"] is None
    assert saved["youtube_id_themerrdb"] == "newfilmthem"
    assert saved["imdb_id"] is None
    assert saved["tvdb_id"] is None
    assert saved["poster_url"] is None
    assert saved["background_url"] is None
    validate_entry(saved)


def test_process_themerr_item_adds_new_show_with_empty_seasons(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    index = EntryIndex.load(data_dir.parent)

    themerr_record = {
        "id": 88888,
        "name": "New Anime Show",
        "first_air_date": "2021-04-01",
        "youtube_theme_url": "https://www.youtube.com/watch?v=anime_theme",
        "poster_path": "/show_poster.jpg",
        "backdrop_path": None,
        "seasons": [
            {"season_number": 0, "poster_path": "/s0.jpg"},
            {"season_number": 1, "poster_path": "/s1.jpg"},
        ],
    }

    status = importer.process_themerr_item(
        themerr_record,
        "show",
        index,
        data_dir,
    )

    assert status == "added"

    target_file = data_dir / "shows" / "tmdb-88888.json"
    assert not target_file.exists()

    saved = index.entries[target_file]
    assert saved["media_type"] == "show"
    assert saved["title"] == "New Anime Show"
    assert saved["year"] == 2021
    assert saved["youtube_id_themerrdb"] == "anime_theme"
    assert saved["youtube_id_overturedb"] is None
    assert saved["poster_url"] is None
    assert saved["background_url"] is None
    assert saved["imdb_id"] is None
    assert saved["tvdb_id"] is None
    assert saved["seasons"] == []
    validate_entry(saved)


def test_process_themerr_item_skips_when_no_theme_or_invalid(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    index = EntryIndex.load(data_dir.parent)

    assert (
        importer.process_themerr_item(
            {"id": 123, "youtube_theme_url": None},
            "movie",
            index,
            data_dir,
        )
    ) == "skipped_no_theme"

    assert (
        importer.process_themerr_item(
            {"id": "not_an_int", "youtube_theme_url": "4xdyx5NVUhI"},
            "movie",
            index,
            data_dir,
        )
    ) == "skipped_invalid"


@dataclass(slots=True, frozen=True)
class Checkout:
    """An OvertureDB checkout beside a ThemerrDB export."""

    root: Path

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def movies(self) -> Path:
        return self.data / "movies"

    @property
    def upstream(self) -> Path:
        return self.root / "upstream"

    @property
    def upstream_movies(self) -> Path:
        return self.upstream / "movies" / "themoviedb"

    @property
    def upstream_shows(self) -> Path:
        return self.upstream / "tv_shows" / "themoviedb"

    def write_existing(self, name: str = "tmdb-1.json", **changes: Any) -> Path:
        path = self.movies / name
        path.write_text(json.dumps(movie(**changes)))
        return path

    def write_upstream(self, name: str = "1.json", **changes: Any) -> Path:
        path = self.upstream_movies / name
        path.write_text(json.dumps({**UPSTREAM_RECORD, **changes}))
        return path

    def run_import(
        self, *, dry_run: bool = False, limit: int | None = None
    ) -> dict[str, int]:
        stats, _ = importer.import_themerrdb(
            self.upstream, self.root, dry_run=dry_run, limit=limit
        )
        return stats


UPSTREAM_RECORD = {
    "id": 1,
    "title": "Imported movie",
    "youtube_theme_url": "https://youtu.be/4xdyx5NVUhI",
}


@pytest.fixture
def checkout(tmp_path: Path) -> Checkout:
    checkout = Checkout(tmp_path)
    checkout.movies.mkdir(parents=True)
    checkout.upstream_movies.mkdir(parents=True)
    checkout.upstream_shows.mkdir(parents=True)
    return checkout


def test_boolean_id_cannot_update_numeric_identity(checkout: Checkout) -> None:
    path = checkout.write_existing()
    before = path.read_bytes()
    checkout.write_upstream(id=True)
    stats = checkout.run_import()
    assert stats["skipped_invalid"] == 1
    assert path.read_bytes() == before


def test_conflicting_identifiers_leave_curated_records_unchanged(
    checkout: Checkout, subtests: pytest.Subtests
) -> None:
    first = checkout.write_existing(imdb_id="tt1")
    second = checkout.write_existing("tmdb-2.json", tmdb_id=2, imdb_id="tt2")
    before = [path.read_bytes() for path in (first, second)]
    conflicts: list[dict[str, Any]] = [
        {"imdb_id": "tt2"},
        {"id": 3, "imdb_id": "tt1"},
        {"imdb_id": "tt3"},
    ]
    for changes in conflicts:
        with subtests.test(changes=changes):
            checkout.write_upstream(**changes)
            assert checkout.run_import()["skipped_error"] == 1
            assert [path.read_bytes() for path in (first, second)] == before


def test_imdb_only_match_preserves_identity(checkout: Checkout) -> None:
    path = checkout.write_existing("imdb-tt1.json", tmdb_id=None, imdb_id="tt1")
    checkout.write_upstream(imdb_id="tt1")
    assert checkout.run_import()["updated"] == 1
    saved = json.loads(path.read_text())
    assert saved["tmdb_id"] is None
    assert saved["youtube_id_themerrdb"] == "4xdyx5NVUhI"
    before = path.read_bytes()
    assert checkout.run_import()["skipped_unchanged"] == 1
    assert path.read_bytes() == before
    assert len(list(checkout.data.rglob("*.json"))) == 1


def test_theme_adopted_by_themerrdb_is_cleared_and_reported(checkout: Checkout) -> None:
    path = checkout.write_existing(
        youtube_id_overturedb="4xdyx5NVUhI",
        youtube_id_themerrdb=None,
    )
    checkout.write_upstream(youtube_theme_url="https://youtu.be/4xdyx5NVUhI")
    stats, lost_themes = importer.import_themerrdb(checkout.upstream, checkout.root)
    assert stats["updated"] == 1
    assert lost_themes == ["A Movie"]
    saved = json.loads(path.read_text())
    assert saved["youtube_id_overturedb"] is None
    assert saved["youtube_id_themerrdb"] == "4xdyx5NVUhI"
    validate_entry(saved)


def test_existing_matching_theme_is_skipped_unchanged(checkout: Checkout) -> None:
    checkout.write_existing(youtube_id_themerrdb="4xdyx5NVUhI")
    checkout.write_upstream()
    assert checkout.run_import()["skipped_unchanged"] == 1


def test_dry_run_and_real_import_agree_for_repeated_new_records(
    checkout: Checkout,
) -> None:
    checkout.write_upstream()
    checkout.write_upstream("duplicate.json")
    planned = checkout.run_import(dry_run=True)
    assert not list(checkout.data.rglob("*.json"))
    assert planned["added"] == 1
    assert planned["skipped_unchanged"] == 1
    assert checkout.run_import() == planned


def test_dry_run_never_changes_existing_file(checkout: Checkout) -> None:
    path = checkout.write_existing()
    before = path.read_bytes()
    checkout.write_upstream()
    assert checkout.run_import(dry_run=True)["updated"] == 1
    assert path.read_bytes() == before


def test_missing_source_folder_fails_before_any_updates(checkout: Checkout) -> None:
    path = checkout.write_existing()
    before = path.read_bytes()
    checkout.write_upstream()
    checkout.upstream_shows.rmdir()
    with pytest.raises(ValueError, match="directory does not exist"):
        checkout.run_import()
    assert path.read_bytes() == before


def test_invalid_existing_file_is_never_overwritten(checkout: Checkout) -> None:
    path = checkout.movies / "tmdb-1.json"
    path.write_text("{broken")
    checkout.write_upstream()
    with pytest.raises(ValueError):
        checkout.run_import()
    assert path.read_text() == "{broken"


def test_duplicate_existing_identities_fail_before_writing(checkout: Checkout) -> None:
    first = checkout.write_existing()
    checkout.write_existing("imdb-tt1.json", imdb_id="tt1")
    before = first.read_bytes()
    checkout.write_upstream()
    with pytest.raises(ValueError, match="Duplicate dataset identity"):
        checkout.run_import()
    assert first.read_bytes() == before


def test_malformed_records_are_reported_and_other_records_are_processed(
    checkout: Checkout, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout.write_upstream()
    (checkout.upstream_movies / "bad.json").write_text("[]")
    (checkout.upstream_movies / "broken.json").write_text("{broken")
    stats = checkout.run_import()
    reported = capsys.readouterr().err
    assert "bad.json" in reported
    assert "broken.json" in reported
    assert stats["skipped_error"] == 2
    assert stats["added"] == 1
    assert list(checkout.data.rglob("*.json")) == []


def test_limit_is_positive_and_applies_across_media_types(checkout: Checkout) -> None:
    checkout.write_upstream()
    (checkout.upstream_shows / "1.json").write_text(
        json.dumps({**UPSTREAM_RECORD, "name": "Imported show"})
    )
    for limit in (0, -1):
        with pytest.raises(ValueError, match="positive integer"):
            checkout.run_import(limit=limit)
    assert checkout.run_import(limit=1)["scanned"] == 1
    assert not (checkout.data / "shows").exists()
    assert checkout.run_import()["added"] == 1
    assert (checkout.data / "shows" / "tmdb-1.json").exists()


@patch.object(importer.publication, "publish")
def test_commit_mode_creates_signed_commit_only_when_entries_change(
    publish: MagicMock,
    checkout: Checkout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "AutoGitr/OvertureDB")
    checkout.write_upstream()
    importer.import_themerrdb(checkout.upstream, checkout.root, commit=True)
    args = publish.call_args.args
    assert args[0] == "AutoGitr/OvertureDB"
    assert args[1] == checkout.root
    plan = args[2](checkout.root)
    assert plan[0] == "Import ThemerrDB themes (1 added, 0 updated)"
    assert "data/movies/tmdb-1.json" in plan[2]
    assert args[3]() is True
    assert not list(checkout.movies.glob("*.json"))
    checkout.run_import()
    assert args[2](checkout.root) is None


def test_cli_reports_missing_input_as_failure(checkout: Checkout) -> None:
    with (
        patch(
            "sys.argv",
            ["import_themerrdb.py", "--themerr-dir", str(checkout.root / "missing")],
        ),
    ):
        assert importer.main() == 1


@patch.object(importer.publication, "publish", side_effect=RuntimeError("head moved"))
def test_failed_commit_preserves_local_dataset_for_retry(
    _commit: MagicMock,
    checkout: Checkout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    checkout.write_upstream()
    with pytest.raises(RuntimeError, match="head moved"):
        importer.import_themerrdb(checkout.upstream, checkout.root, commit=True)
    assert not list(checkout.movies.glob("*.json"))
