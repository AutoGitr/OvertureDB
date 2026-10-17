"""Tests for bulk export import engine enforcing Rule 1 & Rule 2."""

lazy import json
lazy from pathlib import Path
lazy from unittest import mock

lazy import pytest

lazy from scripts.import_bulk_export import (
    create_new_entry,
    import_bulk_export,
    merge_entry,
)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "movies").mkdir(parents=True)
    (data / "shows").mkdir(parents=True)
    return data


def test_rule_1_preserves_existing_artwork_and_theme() -> None:
    existing = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/existing_poster.jpg",
        "background_url": "https://image.tmdb.org/t/p/original/existing_bg.jpg",
        "youtube_id_overturedb": "existing111",
        "youtube_id_themerrdb": None,
    }
    incoming = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/new_poster.jpg",
        "background_url": "https://image.tmdb.org/t/p/original/new_bg.jpg",
        "youtube_id_overturedb": "new11111111",
        "youtube_id_themerrdb": None,
    }
    updated, changed, _changes = merge_entry(existing, incoming)
    assert not changed
    assert (
        updated["poster_url"]
        == "https://image.tmdb.org/t/p/original/existing_poster.jpg"
    )
    assert (
        updated["background_url"]
        == "https://image.tmdb.org/t/p/original/existing_bg.jpg"
    )
    assert updated["youtube_id_overturedb"] == "existing111"


def test_rule_1_backfills_missing_artwork_and_theme() -> None:
    existing = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
    }
    incoming = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/new_poster.jpg",
        "background_url": "https://image.tmdb.org/t/p/original/new_bg.jpg",
        "youtube_id_overturedb": "new11111111",
        "youtube_id_themerrdb": None,
    }
    updated, changed, changes = merge_entry(existing, incoming)
    assert changed
    assert updated["poster_url"] == "https://image.tmdb.org/t/p/original/new_poster.jpg"
    assert updated["background_url"] == "https://image.tmdb.org/t/p/original/new_bg.jpg"
    assert updated["youtube_id_overturedb"] == "new11111111"
    assert "backfilled poster_url" in changes
    assert "backfilled background_url" in changes
    assert "backfilled youtube_id_overturedb" in changes


def test_rule_1_shows_preserves_existing_seasons_and_adds_missing() -> None:
    existing = {
        "media_type": "show",
        "title": "Show",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": 2,
        "imdb_id": None,
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
        "seasons": [
            {
                "season_num": 1,
                "poster_url": "https://image.tmdb.org/t/p/original/season1_exist.jpg",
            }
        ],
    }
    incoming = {
        "media_type": "show",
        "title": "Show",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": 2,
        "imdb_id": None,
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
        "seasons": [
            {
                "season_num": 1,
                "poster_url": "https://image.tmdb.org/t/p/original/season1_new.jpg",
            },
            {
                "season_num": 2,
                "poster_url": "https://image.tmdb.org/t/p/original/season2_new.jpg",
            },
        ],
    }
    updated, changed, _changes = merge_entry(existing, incoming)
    assert changed
    assert len(updated["seasons"]) == 2
    # Season 1 preserved:
    assert (
        updated["seasons"][0]["poster_url"]
        == "https://image.tmdb.org/t/p/original/season1_exist.jpg"
    )
    # Season 2 added:
    assert (
        updated["seasons"][1]["poster_url"]
        == "https://image.tmdb.org/t/p/original/season2_new.jpg"
    )


def test_rule_2_preserves_youtube_id_themerrdb() -> None:
    existing = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": "secondary11",
    }
    incoming = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/p.jpg",
        "background_url": None,
        "youtube_id_overturedb": "primary1111",
        "youtube_id_themerrdb": None,
    }
    updated, changed, _changes = merge_entry(existing, incoming)
    assert changed
    assert updated["youtube_id_themerrdb"] == "secondary11"
    assert updated["youtube_id_overturedb"] == "primary1111"


def test_rule_2_new_entry_has_null_themerrdb_theme(data_dir: Path) -> None:
    incoming = {
        "media_type": "movie",
        "title": "Brand New Movie",
        "year": 2021,
        "tmdb_id": 999,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/p.jpg",
        "background_url": None,
        "youtube_id_overturedb": "primary1111",
        "youtube_id_themerrdb": "should_be_ignored",
    }
    path, entry = create_new_entry(incoming, data_dir)
    assert path.name == "tmdb-999.json"
    assert entry["youtube_id_themerrdb"] is None


def test_conflicting_youtube_id_skips_backfill_overturedb() -> None:
    existing = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": "conflict111",
    }
    incoming = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": "conflict111",
        "youtube_id_themerrdb": None,
    }
    updated, changed, _changes = merge_entry(existing, incoming)
    assert not changed
    assert updated["youtube_id_overturedb"] is None
    assert updated["youtube_id_themerrdb"] == "conflict111"


def test_rejects_conflicting_external_ids() -> None:
    existing = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": "tt1111111",
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
    }
    incoming = {
        "media_type": "movie",
        "title": "Movie",
        "year": 2020,
        "tmdb_id": 2,  # Conflict!
        "tvdb_id": None,
        "imdb_id": "tt1111111",
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
    }
    with pytest.raises(ValueError):
        merge_entry(existing, incoming)


def test_end_to_end_cross_provider_matching(tmp_path: Path, data_dir: Path) -> None:
    # Existing show, found by its TVDB ID
    show_path = data_dir / "shows" / "tmdb-100.json"
    show_path.write_text(
        json.dumps(
            {
                "media_type": "show",
                "title": "My Show",
                "year": 2020,
                "tmdb_id": 100,
                "tvdb_id": 200,
                "imdb_id": None,
                "poster_url": "https://image.tmdb.org/t/p/original/show_poster.jpg",
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": None,
                "seasons": [],
            },
            indent=2,
        )
        + "\n"
    )

    # Incoming export named tmdb-100.json
    input_dir = tmp_path / "export"
    (input_dir / "shows").mkdir(parents=True)
    (input_dir / "shows" / "tmdb-100.json").write_text(
        json.dumps(
            {
                "media_type": "show",
                "title": "My Show",
                "year": 2020,
                "tmdb_id": 100,
                "tvdb_id": 200,
                "imdb_id": None,
                "poster_url": "https://image.tmdb.org/t/p/original/ignored_new_poster.jpg",
                "background_url": "https://image.tmdb.org/t/p/original/new_bg.jpg",
                "youtube_id_overturedb": "showtheme11",
                "youtube_id_themerrdb": None,
                "seasons": [
                    {
                        "season_num": 1,
                        "poster_url": "https://image.tmdb.org/t/p/original/s1.jpg",
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )

    res = import_bulk_export(overture_dir=tmp_path, input_dir=input_dir, dry_run=False)
    assert res["created"] == 0
    assert res["backfilled"] == 1
    assert res["backfilled_kinds"] == {
        "backgrounds": 1,
        "season posters": 1,
        "themes": 1,
    }
    assert res["skipped"] == 0

    # Assert no duplicate entry was created in data/shows
    assert list((data_dir / "shows").glob("*.json")) == [show_path]

    # Assert tmdb-100.json was updated in place with Rule 1 applied
    final_show = json.loads(show_path.read_text())
    assert (
        final_show["poster_url"]
        == "https://image.tmdb.org/t/p/original/show_poster.jpg"
    )
    assert (
        final_show["background_url"] == "https://image.tmdb.org/t/p/original/new_bg.jpg"
    )
    assert final_show["youtube_id_overturedb"] == "showtheme11"
    assert len(final_show["seasons"]) == 1


@mock.patch("scripts.import_bulk_export.MAX_ARCHIVE_ENTRIES", 5)
@pytest.mark.usefixtures("data_dir")
def test_rejection_over_max_entries_archive(tmp_path: Path) -> None:
    import zipfile

    zip_path = tmp_path / "too_many.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(6):
            zf.writestr(f"movie_{i}.json", "{}")
    with pytest.raises(ValueError) as ctx:
        import_bulk_export(overture_dir=tmp_path, archive_path=zip_path)
    assert "exceeds maximum allowed entries" in str(ctx.value)


@pytest.mark.usefixtures("data_dir")
def test_rejection_over_1mb_file_archive(tmp_path: Path) -> None:
    import zipfile

    zip_path = tmp_path / "too_large_entry.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("large.json", " " * (1024 * 1024 + 1))
    with pytest.raises(ValueError) as ctx:
        import_bulk_export(overture_dir=tmp_path, archive_path=zip_path)
    assert "exceeds maximum size" in str(ctx.value)


@mock.patch("scripts.import_bulk_export.MAX_ARCHIVE_ENTRIES", 5)
@pytest.mark.usefixtures("data_dir")
def test_rejection_over_max_entries_directory(tmp_path: Path) -> None:
    large_dir = tmp_path / "large_dir"
    large_dir.mkdir()
    for i in range(6):
        (large_dir / f"entry_{i}.json").write_text("{}")
    with pytest.raises(ValueError) as ctx:
        import_bulk_export(overture_dir=tmp_path, input_dir=large_dir)
    assert "exceeds maximum allowed entries" in str(ctx.value)


@pytest.mark.usefixtures("data_dir")
def test_rejection_over_1mb_file_directory(tmp_path: Path) -> None:
    large_dir = tmp_path / "large_file_dir"
    large_dir.mkdir()
    (large_dir / "huge.json").write_text(" " * (1024 * 1024 + 1))
    with pytest.raises(ValueError) as ctx:
        import_bulk_export(overture_dir=tmp_path, input_dir=large_dir)
    assert "exceeds maximum size" in str(ctx.value)


def test_partial_import_writes_changes_and_reports_errors(
    tmp_path: Path, data_dir: Path
) -> None:
    valid_entry = {
        "media_type": "movie",
        "title": "Valid Movie",
        "year": 2024,
        "tmdb_id": 999999,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/valid.jpg",
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
    }
    invalid_entry = {
        "media_type": "movie",
        "title": "Invalid Movie",
        "year": 2024,
        "tmdb_id": 888888,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://m.media-amazon.com/invalid.jpg",
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
    }
    input_dir = tmp_path / "mixed_input"
    input_dir.mkdir()
    (input_dir / "tmdb-999999.json").write_text(json.dumps(valid_entry))
    (input_dir / "tmdb-888888.json").write_text(json.dumps(invalid_entry))
    res = import_bulk_export(overture_dir=tmp_path, input_dir=input_dir, dry_run=False)
    assert res["created"] == 1
    assert len(res["errors"]) == 1
    assert (data_dir / "movies" / "tmdb-999999.json").exists()
    assert not (data_dir / "movies" / "tmdb-888888.json").exists()


def test_format_review_markdown_sorting_and_links() -> None:
    from scripts.import_bulk_export import ReviewItem, format_review_markdown

    items = [
        ReviewItem(
            title="Zoolander",
            year=2001,
            media_type="movie",
            poster_url="https://image.tmdb.org/t/p/original/zoolander.jpg",
            youtube_id="zoo12345678",
        ),
        ReviewItem(
            title="Avatar",
            year=2009,
            media_type="movie",
            background_url="https://image.tmdb.org/t/p/original/avatar_bg.jpg",
        ),
        ReviewItem(
            title="Breaking Bad",
            year=2008,
            media_type="show",
            seasons=[(1, "https://image.tmdb.org/t/p/original/bb_s1.jpg")],
        ),
    ]
    md = format_review_markdown(items)
    assert "<details>" in md
    assert "<summary><b>Review Artwork & Theme URLs (3 items)</b></summary>" in md

    # Check alphabetical ordering: Avatar -> Breaking Bad -> Zoolander
    idx_avatar = md.index("Avatar (2009)")
    idx_bb = md.index("Breaking Bad (2008)")
    idx_zoolander = md.index("Zoolander (2001)")
    assert idx_avatar < idx_bb < idx_zoolander

    # Check clickable links
    assert "[View image](<https://image.tmdb.org/t/p/original/avatar_bg.jpg>)" in md
    assert "[View image](<https://image.tmdb.org/t/p/original/zoolander.jpg>)" in md
    assert "[Watch video](https://www.youtube.com/watch?v=zoo12345678)" in md
    assert "[View image](<https://image.tmdb.org/t/p/original/bb_s1.jpg>)" in md


def test_review_that_does_not_fit_is_refused() -> None:
    from scripts.import_bulk_export import ReviewItem, format_review_markdown

    items = [
        ReviewItem(
            title=f"Movie {i:03d}",
            year=2020,
            media_type="movie",
            poster_url=f"https://image.tmdb.org/t/p/original/poster_{i}.jpg",
        )
        for i in range(50)
    ]
    with pytest.raises(ValueError, match="Split the export"):
        format_review_markdown(items, max_chars=500)


def test_review_lists_added_identifiers() -> None:
    from scripts.import_bulk_export import ReviewItem, format_review_markdown

    item = ReviewItem(
        title="Movie", year=2020, media_type="movie", added=["imdb_id=tt1"]
    )
    assert "- **Added:** `imdb_id=tt1`" in format_review_markdown([item])
