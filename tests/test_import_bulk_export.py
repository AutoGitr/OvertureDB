"""Tests for bulk export import engine enforcing Rule 1 & Rule 2."""

lazy import json
lazy import zipfile
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest import mock

lazy import pytest

lazy from scripts.import_bulk_export import (
    Change,
    Outcome,
    ReviewItem,
    create_new_entry,
    format_review_markdown,
    import_bulk_export,
    merge_entry,
)
lazy from tests.changes import apply_changes


def entry_count(result: dict[str, Any], outcome: Outcome) -> int:
    """How many entries a bulk import gave *outcome*."""
    return sum(result["entries"][outcome].values())


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
    updated = merge_entry(existing, incoming)
    assert updated == existing
    assert (
        updated["poster_url"]
        == "https://image.tmdb.org/t/p/original/existing_poster.jpg"
    )
    assert (
        updated["background_url"]
        == "https://image.tmdb.org/t/p/original/existing_bg.jpg"
    )
    assert updated["youtube_id_overturedb"] == "existing111"


def test_an_admin_import_replaces_held_artwork_seasons_and_theme() -> None:
    held = "https://image.tmdb.org/t/p/original/held.jpg"
    new = "https://image.tmdb.org/t/p/original/new.jpg"
    existing = {
        "media_type": "show",
        "title": "Show",
        "year": 2020,
        "tmdb_id": 1,
        "tvdb_id": 2,
        "imdb_id": None,
        "poster_url": held,
        "background_url": held,
        "seasons": [{"season_num": 1, "poster_url": held}],
        "youtube_id_overturedb": "held1111111",
        "youtube_id_themerrdb": "imported111",
    }
    incoming = {
        **existing,
        "poster_url": new,
        "background_url": None,
        "seasons": [{"season_num": 1, "poster_url": new}],
        "youtube_id_overturedb": "new11111111",
        "youtube_id_themerrdb": None,
    }

    updated = merge_entry(existing, incoming, overwrite=True)

    # An empty incoming value keeps what the entry holds.
    assert (updated["poster_url"], updated["background_url"]) == (new, held)
    assert updated["seasons"] == [{"season_num": 1, "poster_url": new}]
    assert updated["youtube_id_overturedb"] == "new11111111"
    assert updated["youtube_id_themerrdb"] == "imported111"
    assert merge_entry(existing, incoming) == existing


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
    updated = merge_entry(existing, incoming)
    assert updated != existing
    assert updated["poster_url"] == "https://image.tmdb.org/t/p/original/new_poster.jpg"
    assert updated["background_url"] == "https://image.tmdb.org/t/p/original/new_bg.jpg"
    assert updated["youtube_id_overturedb"] == "new11111111"


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
    updated = merge_entry(existing, incoming)
    assert updated != existing
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
    updated = merge_entry(existing, incoming)
    assert updated != existing
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
    updated = merge_entry(existing, incoming)
    assert updated == existing
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
    with pytest.raises(
        ValueError, match=r"Conflicting tmdb_id: existing=1, incoming=2"
    ):
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

    res = apply_changes(
        tmp_path, import_bulk_export(overture_dir=tmp_path, input_dir=input_dir)
    )
    assert entry_count(res, "new") == 0
    assert entry_count(res, "updated") == 1
    assert res["entries"]["updated"] == {"show": 1}
    assert res["changes"] == {
        "backgrounds": {"filled": 1},
        "season posters": {"filled": 1},
        "themes": {"filled": 1},
    }
    assert len(res["errors"]) == 0

    # The show is updated in place, not added again.
    assert list((data_dir / "shows").glob("*.json")) == [show_path]

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
    zip_path = tmp_path / "too_many.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for i in range(6):
            zf.writestr(f"movie_{i}.json", "{}")
    with pytest.raises(
        ValueError, match=r"Input exceeds maximum allowed entries \(5\)"
    ) as ctx:
        import_bulk_export(overture_dir=tmp_path, archive_path=zip_path)
    assert "exceeds maximum allowed entries" in str(ctx.value)


@pytest.mark.usefixtures("data_dir")
def test_rejection_over_1mb_file_archive(tmp_path: Path) -> None:
    zip_path = tmp_path / "too_large_entry.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("large.json", " " * (1024 * 1024 + 1))
    with pytest.raises(
        ValueError, match=r"large\.json exceeds maximum size \(1 MB\)"
    ) as ctx:
        import_bulk_export(overture_dir=tmp_path, archive_path=zip_path)
    assert "exceeds maximum size" in str(ctx.value)


@mock.patch("scripts.import_bulk_export.MAX_ARCHIVE_ENTRIES", 5)
@pytest.mark.usefixtures("data_dir")
def test_rejection_over_max_entries_directory(tmp_path: Path) -> None:
    large_dir = tmp_path / "large_dir"
    large_dir.mkdir()
    for i in range(6):
        (large_dir / f"entry_{i}.json").write_text("{}")
    with pytest.raises(
        ValueError, match=r"Input exceeds maximum allowed entries \(5\)"
    ) as ctx:
        import_bulk_export(overture_dir=tmp_path, input_dir=large_dir)
    assert "exceeds maximum allowed entries" in str(ctx.value)


@pytest.mark.usefixtures("data_dir")
def test_rejection_over_1mb_file_directory(tmp_path: Path) -> None:
    large_dir = tmp_path / "large_file_dir"
    large_dir.mkdir()
    (large_dir / "huge.json").write_text(" " * (1024 * 1024 + 1))
    with pytest.raises(
        ValueError, match=r"huge\.json exceeds maximum size \(1 MB\)"
    ) as ctx:
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
    res = apply_changes(
        tmp_path, import_bulk_export(overture_dir=tmp_path, input_dir=input_dir)
    )
    assert entry_count(res, "new") == 1
    assert len(res["errors"]) == 1
    assert (data_dir / "movies" / "tmdb-999999.json").exists()
    assert not (data_dir / "movies" / "tmdb-888888.json").exists()


def _review(
    title: str,
    media_type: str,
    outcome: Outcome,
    *changes: Change,
    year: int | None = None,
) -> ReviewItem:
    return ReviewItem(title, year, media_type, outcome, list(changes))


def _poster(url: str, old: str | None = None) -> Change:
    return Change("posters", "Poster", url, old)


def test_review_groups_entries_by_outcome_then_type_alphabetically() -> None:
    image = "https://image.tmdb.org/t/p/original"
    items = [
        _review("Zoolander", "movie", "new", _poster(f"{image}/z.jpg"), year=2001),
        _review("Avatar", "movie", "new", _poster(f"{image}/a.jpg"), year=2009),
        _review("Andor", "show", "new", _poster(f"{image}/andor.jpg"), year=2022),
        _review(
            "Alien Collection",
            "collection",
            "updated",
            Change("backgrounds", "Background", f"{image}/alien.jpg"),
        ),
        _review(
            "Breaking Bad",
            "show",
            "overwritten",
            Change(
                "season posters",
                "Season 1 poster",
                f"{image}/s1.jpg",
                f"{image}/old.jpg",
            ),
            Change("themes", "Theme", "new11111111", "old11111111"),
            year=2008,
        ),
    ]
    md = format_review_markdown(items)

    overwritten = md.index("<details open>\n<summary><b>Overwritten (1)</b></summary>")
    updated = md.index("<summary><b>Filled gaps (1)</b></summary>")
    new = md.index("<summary><b>New entries (3)</b></summary>")
    assert overwritten < updated < new
    in_new = md[new:]
    assert in_new.index("### Movies") < in_new.index("#### Avatar (2009)")
    assert in_new.index("#### Avatar (2009)") < in_new.index("#### Zoolander (2001)")
    assert in_new.index("#### Zoolander (2001)") < in_new.index("### Shows")
    assert f"- **Poster:** [View image](<{image}/a.jpg>)" in md
    assert (
        f"- **Season 1 poster:** [Current](<{image}/old.jpg>) → [New](<{image}/s1.jpg>)"
    ) in md
    assert (
        "- **Theme:** [Current](https://www.youtube.com/watch?v=old11111111) → "
        "[New](https://www.youtube.com/watch?v=new11111111)"
    ) in md


def test_review_that_does_not_fit_is_refused() -> None:
    items = [
        _review(
            f"Movie {i:03d}",
            "movie",
            "new",
            _poster(f"https://image.tmdb.org/t/p/original/poster_{i}.jpg"),
        )
        for i in range(50)
    ]
    with pytest.raises(ValueError, match="Split the export"):
        format_review_markdown(items, max_chars=500)


def test_review_lists_added_identifiers() -> None:
    item = _review(
        "Movie",
        "movie",
        "updated",
        Change("identifiers", "imdb_id", "tt1"),
        _poster("https://image.tmdb.org/t/p/original/p.jpg"),
    )
    assert "- **Added:** `imdb_id=tt1`" in format_review_markdown([item])


def test_id_only_backfills_do_not_populate_review_markdown(
    tmp_path: Path, data_dir: Path
) -> None:
    entry = {
        "media_type": "movie",
        "title": "Existing Film",
        "year": 2020,
        "tmdb_id": 100,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/p.jpg",
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
    }
    movies_dir = data_dir / "movies"
    (movies_dir / "tmdb-100.json").write_text(json.dumps(entry))
    incoming = dict(entry)
    incoming["tvdb_id"] = 200
    incoming["imdb_id"] = "tt0000100"
    input_dir = tmp_path / "id_input"
    input_dir.mkdir()
    (input_dir / "tmdb-100.json").write_text(json.dumps(incoming))
    res = apply_changes(
        tmp_path, import_bulk_export(overture_dir=tmp_path, input_dir=input_dir)
    )
    assert entry_count(res, "new") == 0
    assert entry_count(res, "updated") == 1
    assert res["changes"] == {"identifiers": {"filled": 2}}
    assert res["review_markdown"] == ""
    saved = json.loads((movies_dir / "tmdb-100.json").read_text())
    assert saved["tvdb_id"] == 200
    assert saved["imdb_id"] == "tt0000100"


def test_created_kinds_tracks_new_entry_media(tmp_path: Path, data_dir: Path) -> None:
    input_dir = tmp_path / "new_input"
    input_dir.mkdir()
    new_movie = {
        "media_type": "movie",
        "title": "Brand New Film",
        "year": 2024,
        "tmdb_id": 999,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/new.jpg",
        "background_url": "https://image.tmdb.org/t/p/original/bg.jpg",
        "youtube_id_overturedb": "abc12345678",
        "youtube_id_themerrdb": None,
    }
    (input_dir / "tmdb-999.json").write_text(json.dumps(new_movie))
    res = import_bulk_export(overture_dir=tmp_path, input_dir=input_dir)
    assert entry_count(res, "new") == 1
    assert res["entries"]["new"] == {"movie": 1}
    assert res["changes"] == {
        "posters": {"added": 1},
        "backgrounds": {"added": 1},
        "themes": {"added": 1},
    }


def test_created_collection_keeps_consistent_poster_without_own_poster(
    tmp_path: Path, data_dir: Path
) -> None:
    (data_dir / "collections").mkdir(parents=True)
    input_dir = tmp_path / "collection_input"
    input_dir.mkdir()
    collection_entry = {
        "media_type": "collection",
        "title": "Dune Collection",
        "tmdb_id": 726871,
        "poster_url_individual": None,
        "poster_url_matte": "https://theposterdb.com/api/assets/668235",
        "poster_url_overlay": "https://theposterdb.com/api/assets/229582",
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
    }
    (input_dir / "tmdb-726871.json").write_text(json.dumps(collection_entry))

    res = apply_changes(
        tmp_path, import_bulk_export(overture_dir=tmp_path, input_dir=input_dir)
    )

    assert res["errors"] == []
    assert entry_count(res, "new") == 1
    assert res["entries"]["new"] == {"collection": 1}
    assert res["changes"] == {"posters": {"added": 2}}
    saved = json.loads((data_dir / "collections" / "tmdb-726871.json").read_text())
    assert saved == collection_entry
