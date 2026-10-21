"""Unit tests for contribution parsing, duplicate handling, and modifications."""

lazy import json
lazy from pathlib import Path

lazy import pytest

lazy from scripts.catalog import entry_path, new_entry
lazy from scripts.contribution import (
    clean_art_url,
    clean_youtube_id,
    extract_field,
    format_media_comparison,
    parse_issue_form,
    process_contribution,
)

EMPTY_REASON = "_No response_"
REASON_HEADING = "Reason for modification"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    (data / "movies").mkdir(parents=True)
    (data / "shows").mkdir(parents=True)
    return data


def test_clean_art_url() -> None:
    assert clean_art_url(None) is None
    assert clean_art_url("") is None
    tpdb = "https://theposterdb.com/api/assets/12345/view"
    assert clean_art_url(tpdb) == "https://theposterdb.com/api/assets/12345"
    assert clean_art_url(f"{tpdb}/") == "https://theposterdb.com/api/assets/12345"
    normal = "https://image.tmdb.org/t/p/original/test.jpg"
    assert clean_art_url(normal) == normal


def test_extract_field() -> None:
    body = """### Title

Inception

### Year

2010

### TVDB ID

_No response_
"""
    assert extract_field(body, "Title") == "Inception"
    assert extract_field(body, "Year") == "2010"
    assert extract_field(body, "TVDB ID") is None
    assert extract_field(body, "Nonexistent") is None


def test_parse_movie_form() -> None:
    body = f"""### Title

Interstellar

### Year

2014

### TMDB ID

157336

### IMDb ID

tt0816692

### Poster URL

https://image.tmdb.org/t/p/original/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg

### YouTube theme video ID

abc123abc12

### Reason for modification

{EMPTY_REASON}
"""
    parsed = parse_issue_form(body, "[Movie]: Interstellar (2014)", ["movie"])
    assert parsed.media_type == "movie"
    assert parsed.title == "Interstellar"
    assert parsed.year == 2014
    assert parsed.tmdb_id == 157336
    assert parsed.tvdb_id is None
    assert parsed.imdb_id == "tt0816692"
    assert parsed.youtube_id == "abc123abc12"
    assert parsed.modification_reason is None


def test_parse_invalid_fields() -> None:
    base_body = "### Title\n\nMovie\n\n### TMDB ID\n\nabc"
    with pytest.raises(ValueError) as ctx:
        parse_issue_form(base_body, "[Movie]: Movie", ["movie"])
    assert "TMDB ID must contain digits only" in str(ctx.value)

    body_bad_imdb = "### Title\n\nMovie\n\n### IMDb ID\n\n12345"
    with pytest.raises(ValueError) as ctx:
        parse_issue_form(body_bad_imdb, "[Movie]: Movie", ["movie"])
    assert "IMDb ID must use the format tt" in str(ctx.value)

    body_bad_yt = (
        "### Title\n\nMovie\n\n### TMDB ID\n\n1\n\n"
        "### YouTube theme video ID\n\nhttp://yt.com"
    )
    with pytest.raises(ValueError) as ctx:
        parse_issue_form(body_bad_yt, "[Movie]: Movie", ["movie"])
    assert "Invalid YouTube theme ID or URL" in str(ctx.value)


def test_entry_path_names_movies_and_shows_by_tmdb_first(data_dir: Path) -> None:
    ids = {"tmdb_id": 100, "tvdb_id": 200, "imdb_id": "tt123"}
    movie_path = entry_path(new_entry("movie", "Movie", **ids), data_dir)
    assert movie_path.name == "tmdb-100.json"
    assert movie_path.parent.name == "movies"

    show_path = entry_path(new_entry("show", "Show", **ids), data_dir)
    assert show_path.name == "tmdb-100.json"
    tvdb_only = new_entry("show", "Show", tvdb_id=200, imdb_id="tt123")
    assert entry_path(tvdb_only, data_dir).name == "tvdb-200.json"
    assert show_path.parent.name == "shows"


@pytest.mark.usefixtures("data_dir")
def test_new_entry_creation(tmp_path: Path) -> None:
    body = """### Title

New Movie

### Year

2024

### TMDB ID

88888

### Poster URL

https://image.tmdb.org/t/p/original/new_movie.jpg

### Reason for modification

_No response_
"""
    parsed = parse_issue_form(body, "[Movie]: New Movie (2024)", ["movie"])
    res = process_contribution(parsed, tmp_path, dry_run=False)

    assert res["status"] == "ok"
    assert not res["is_modification"]
    assert res["target"] == "data/movies/tmdb-88888.json"
    assert (tmp_path / "data/movies/tmdb-88888.json").is_file()


@pytest.mark.usefixtures("data_dir")
def test_new_entry_without_media_rejected(tmp_path: Path) -> None:
    body = """### Title

Empty Movie

### Year

2024

### TMDB ID

77777
"""
    parsed = parse_issue_form(body, "[Movie]: Empty Movie (2024)", ["movie"])
    with pytest.raises(ValueError) as ctx:
        process_contribution(parsed, tmp_path, dry_run=False)
    assert "New entry contributions must include at least one artwork URL" in str(
        ctx.value
    )


def test_existing_entry_blocks_without_modification_reason(
    tmp_path: Path, data_dir: Path
) -> None:
    existing_file = data_dir / "movies" / "tmdb-88888.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Existing Movie",
                "year": 2024,
                "tmdb_id": 88888,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": "https://image.tmdb.org/t/p/original/p.jpg",
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": None,
            },
            indent=2,
        )
        + "\n"
    )

    body = f"""### Title

Existing Movie

### Year

2024

### TMDB ID

88888

### Poster URL

https://image.tmdb.org/t/p/original/new_p.jpg

### Reason for modification

{EMPTY_REASON}
"""
    parsed = parse_issue_form(body, "[Movie]: Existing Movie (2024)", ["movie"])
    with pytest.raises(ValueError) as ctx:
        process_contribution(parsed, tmp_path, dry_run=False)
    assert "needs a reason" in str(ctx.value)


def test_title_or_year_change_requires_modification_reason(
    subtests: pytest.Subtests,
    tmp_path: Path,
    data_dir: Path,
) -> None:
    existing_file = data_dir / "movies" / "tmdb-88888.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Existing Movie",
                "year": 2024,
                "tmdb_id": 88888,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": "https://image.tmdb.org/t/p/original/p.jpg",
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": None,
            },
            indent=2,
        )
        + "\n"
    )
    for title, year in (("Localized Title", 2024), ("Existing Movie", 2025)):
        body = f"""### Title

{title}

### Year

{year}

### TMDB ID

88888

### Background URL

https://image.tmdb.org/t/p/original/bg.jpg
"""
        with subtests.test(title=title, year=year):
            parsed = parse_issue_form(body, f"[Movie]: {title} ({year})", ["movie"])
            with pytest.raises(ValueError, match="needs a reason"):
                process_contribution(parsed, tmp_path, dry_run=True)


def test_backfill_stub_without_modification_reason(
    tmp_path: Path, data_dir: Path
) -> None:
    existing_file = data_dir / "movies" / "tmdb-11104.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Chungking Express",
                "year": 1994,
                "tmdb_id": 11104,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": None,
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": "xwGZvpRf1GA",
            },
            indent=2,
        )
        + "\n"
    )

    body = f"""### Title

Chungking Express

### Year

1994

### TMDB ID

11104

### TVDB ID

4982

### IMDb ID

tt0109424

### Poster URL

https://image.tmdb.org/t/p/original/poster.jpg

### Background URL

https://image.tmdb.org/t/p/original/bg.jpg

### Reason for modification

{EMPTY_REASON}
"""
    parsed = parse_issue_form(body, "[Movie]: Chungking Express (1994)", ["movie"])
    res = process_contribution(parsed, tmp_path, dry_run=False)

    assert res["status"] == "ok"
    assert not res["is_modification"]
    assert res["is_addition"]
    assert res["target"] == "data/movies/tmdb-11104.json"
    assert res["tvdb_id"] == 4982
    assert res["imdb_id"] == "tt0109424"
    assert res["youtube_id"] is None

    saved = json.loads(existing_file.read_text())
    assert saved["poster_url"] == "https://image.tmdb.org/t/p/original/poster.jpg"
    assert saved["background_url"] == "https://image.tmdb.org/t/p/original/bg.jpg"
    assert saved["youtube_id_themerrdb"] == "xwGZvpRf1GA"
    assert saved["tvdb_id"] == 4982
    assert saved["imdb_id"] == "tt0109424"


def test_submitting_matching_themerrdb_theme_does_not_duplicate_or_fail(
    tmp_path: Path,
    data_dir: Path,
) -> None:
    existing_file = data_dir / "movies" / "tmdb-11104.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Chungking Express",
                "year": 1994,
                "tmdb_id": 11104,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": None,
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": "xwGZvpRf1GA",
            },
            indent=2,
        )
        + "\n"
    )

    body = f"""### Title

Chungking Express

### Year

1994

### TMDB ID

11104

### Poster URL

https://image.tmdb.org/t/p/original/poster.jpg

### YouTube theme video ID

xwGZvpRf1GA

### Reason for modification

{EMPTY_REASON}
"""
    parsed = parse_issue_form(body, "[Movie]: Chungking Express (1994)", ["movie"])
    res = process_contribution(parsed, tmp_path, dry_run=False)

    assert res["status"] == "ok"
    assert not res["is_modification"]
    assert res["is_addition"]
    assert res["youtube_id"] is None

    saved = json.loads(existing_file.read_text())
    assert saved["poster_url"] == "https://image.tmdb.org/t/p/original/poster.jpg"
    assert saved["youtube_id_themerrdb"] == "xwGZvpRf1GA"
    assert saved["youtube_id_overturedb"] is None


def test_existing_entry_allows_with_modification_reason(
    tmp_path: Path, data_dir: Path
) -> None:
    existing_file = data_dir / "movies" / "tmdb-88888.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Existing Movie",
                "year": 2024,
                "tmdb_id": 88888,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": "https://image.tmdb.org/t/p/original/old_poster.jpg",
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": "themerr1111",
            },
            indent=2,
        )
        + "\n"
    )

    body = """### Title

Existing Movie

### Year

2024

### TMDB ID

88888

### Poster URL

https://image.tmdb.org/t/p/original/new_higher_res_poster.jpg

### Reason for modification

Upgrading to official 4K poster art.
"""
    parsed = parse_issue_form(body, "[Movie]: Existing Movie (2024)", ["movie"])
    res = process_contribution(parsed, tmp_path, dry_run=False)

    assert res["status"] == "ok"
    assert res["is_modification"]
    assert res["modification_reason"] == "Upgrading to official 4K poster art."
    assert "new_higher_res_poster.jpg" in res["diff"]

    assert (
        "- **Poster:** [Old](https://image.tmdb.org/t/p/original/old_poster.jpg) | "
        "[New](https://image.tmdb.org/t/p/original/new_higher_res_poster.jpg)"
    ) in res["media_comparison"]
    assert "Background" not in res["media_comparison"]
    assert "YouTube" not in res["media_comparison"]

    updated_data = json.loads(existing_file.read_text())
    assert (
        updated_data["poster_url"]
        == "https://image.tmdb.org/t/p/original/new_higher_res_poster.jpg"
    )
    assert updated_data["youtube_id_themerrdb"] == "themerr1111"


def test_format_media_comparison_all_types() -> None:
    existing = {
        "poster_url": "https://image.tmdb.org/t/p/original/old_poster.jpg",
        "background_url": "https://image.tmdb.org/t/p/original/old_bg.jpg",
        "youtube_id_themerrdb": None,
        "youtube_id_overturedb": "oldtheme123",
        "seasons": [
            {
                "season_num": 1,
                "poster_url": "https://image.tmdb.org/t/p/original/old_s1.jpg",
            },
        ],
    }
    updated = {
        # Unchanged
        "poster_url": "https://image.tmdb.org/t/p/original/old_poster.jpg",
        # Changed
        "background_url": "https://image.tmdb.org/t/p/original/new_bg.jpg",
        "youtube_id_themerrdb": "oldtheme123",
        "youtube_id_overturedb": "newtheme456",  # Changed
        "seasons": [
            {
                "season_num": 1,
                "poster_url": "https://image.tmdb.org/t/p/original/new_s1.jpg",
            },  # Changed
            {
                "season_num": 2,
                "poster_url": "https://image.tmdb.org/t/p/original/new_s2.jpg",
            },  # Added
        ],
    }
    markdown = format_media_comparison(existing, updated)

    assert "Poster" not in markdown.splitlines()[0]  # Poster didn't change
    assert (
        "- **Background:** [Old](https://image.tmdb.org/t/p/original/old_bg.jpg) | "
        "[New](https://image.tmdb.org/t/p/original/new_bg.jpg)"
    ) in markdown
    assert (
        "- **YouTube Theme:** [Old](https://www.youtube.com/watch?v=oldtheme123) | "
        "[New](https://www.youtube.com/watch?v=newtheme456)"
    ) in markdown
    assert (
        "- **Season 1 Poster:** "
        "[Old](https://image.tmdb.org/t/p/original/old_s1.jpg) | "
        "[New](https://image.tmdb.org/t/p/original/new_s1.jpg)"
    ) in markdown
    assert (
        "- **Season 2 Poster:** _None_ | [New](https://image.tmdb.org/t/p/original/new_s2.jpg)"
        in markdown
    )


def test_theme_comparison_only_shows_contributed_theme() -> None:
    existing = {"youtube_id_themerrdb": "oldtheme123"}
    updated = {**existing, "youtube_id_overturedb": "newtheme456"}
    assert format_media_comparison(existing, updated) == (
        "- **YouTube Theme:** _None_ | "
        "[New](https://www.youtube.com/watch?v=newtheme456)"
    )
    assert format_media_comparison(existing, {}) == ""
    assert format_media_comparison(updated, existing) == (
        "- **YouTube Theme:** [Old](https://www.youtube.com/watch?v=newtheme456)"
        " | _None_"
    )


def test_identifier_correction_is_a_modification_and_renames_the_file(
    tmp_path: Path,
    data_dir: Path,
) -> None:
    old = data_dir / "movies" / "tmdb-1.json"
    entry = new_entry(
        "movie",
        "Movie",
        tmdb_id=1,
        imdb_id="tt1",
        poster_url="https://image.tmdb.org/t/p/original/p.jpg",
    )
    old.write_text(json.dumps(entry, indent=2) + "\n")
    body = f"""### Title

Movie

### TMDB ID

2

### IMDb ID

tt1

### {REASON_HEADING}

{EMPTY_REASON}
"""
    parsed = parse_issue_form(body, "[Movie]: Movie", ["movie"])
    with pytest.raises(ValueError, match="needs a reason"):
        process_contribution(parsed, tmp_path)
    parsed = parse_issue_form(
        body + "TMDB 1 is a different film.\n", "[Movie]: Movie", ["movie"]
    )
    result = process_contribution(parsed, tmp_path)
    assert result["is_modification"]
    assert result["target"] == "data/movies/tmdb-2.json"
    assert not old.exists()
    saved = json.loads((data_dir / "movies/tmdb-2.json").read_text())
    assert (saved["tmdb_id"], saved["imdb_id"]) == (2, "tt1")


def test_removal_needs_a_reason_and_deletes_the_entry(
    tmp_path: Path, data_dir: Path
) -> None:
    path = data_dir / "movies" / "tmdb-1.json"
    entry = new_entry(
        "movie",
        "Movie",
        tmdb_id=1,
        poster_url="https://image.tmdb.org/t/p/original/p.jpg",
    )
    path.write_text(json.dumps(entry, indent=2) + "\n")
    body = f"""### Title

Movie

### TMDB ID

1

### {REASON_HEADING}

_No response_

### Removal

- [X] Remove this entry from the dataset
"""
    parsed = parse_issue_form(body, "[Movie]: Movie", ["movie"])
    assert parsed.remove
    with pytest.raises(ValueError, match="needs a reason"):
        process_contribution(parsed, tmp_path)
    parsed = parse_issue_form(
        body.replace("_No response_", "Not a real film."),
        "[Movie]: Movie",
        ["movie"],
    )
    result = process_contribution(parsed, tmp_path)
    assert result["removed"]
    assert "+++ /dev/null" in result["diff"]
    assert not path.exists()


def test_unchecked_removal_keeps_the_entry() -> None:
    body = """### Title

Movie

### TMDB ID

1

### Removal

- [ ] Remove this entry from the dataset
"""
    assert not parse_issue_form(body, "[Movie]: Movie", ["movie"]).remove


def test_cross_provider_matching_for_shows(tmp_path: Path, data_dir: Path) -> None:
    # Existing show stored as tmdb-1234.json, found by its TVDB ID
    show_file = data_dir / "shows" / "tmdb-1234.json"
    show_file.write_text(
        json.dumps(
            {
                "media_type": "show",
                "title": "My Show",
                "year": 2021,
                "tmdb_id": 1234,
                "tvdb_id": 500,
                "imdb_id": None,
                "poster_url": "https://image.tmdb.org/t/p/original/show.jpg",
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": None,
                "seasons": [],
            },
            indent=2,
        )
        + "\n"
    )

    # Contributor submits using only TMDB ID 1234
    body = """### Title

My Show

### Year

2021

### TMDB ID

1234

### Background URL

https://image.tmdb.org/t/p/original/new_background.jpg

### Reason for modification

Adding missing backdrop.
"""
    parsed = parse_issue_form(body, "[Show]: My Show", ["show"])
    res = process_contribution(parsed, tmp_path, dry_run=False)

    assert not res["is_modification"]
    assert res["is_addition"]
    assert res["target"] == "data/shows/tmdb-1234.json"

    # Updated in place: no duplicate entry was created
    assert list((data_dir / "shows").glob("*.json")) == [show_file]

    updated = json.loads(show_file.read_text())
    assert (
        updated["background_url"]
        == "https://image.tmdb.org/t/p/original/new_background.jpg"
    )
    assert updated["tvdb_id"] == 500


def test_replacing_theme_requires_reason(tmp_path: Path, data_dir: Path) -> None:
    existing_file = data_dir / "movies" / "tmdb-999.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Theme Movie",
                "year": 2020,
                "tmdb_id": 999,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": None,
                "background_url": None,
                "youtube_id_overturedb": "oldTheme111",
                "youtube_id_themerrdb": None,
            },
            indent=2,
        )
        + "\n"
    )

    # Replacing theme without reason blocks
    body = f"""### Title

Theme Movie

### Year

2020

### TMDB ID

999

### YouTube theme video ID

newTheme222

### Reason for modification

{EMPTY_REASON}
"""
    parsed = parse_issue_form(body, "[Movie]: Theme Movie (2020)", ["movie"])
    with pytest.raises(ValueError) as ctx:
        process_contribution(parsed, tmp_path, dry_run=False)
    assert "needs a reason" in str(ctx.value)

    # Replacing theme with reason succeeds
    body_with_reason = body.replace(EMPTY_REASON, "Better audio quality theme.")
    parsed_ok = parse_issue_form(
        body_with_reason, "[Movie]: Theme Movie (2020)", ["movie"]
    )
    res = process_contribution(parsed_ok, tmp_path, dry_run=False)
    assert res["is_modification"]
    assert res["youtube_id"] == "newTheme222"
    assert (
        "- **YouTube Theme:** [Old](https://www.youtube.com/watch?v=oldTheme111) | "
        "[New](https://www.youtube.com/watch?v=newTheme222)"
    ) in res["media_comparison"]


def test_adding_overturedb_theme_when_themerrdb_exists_is_not_modification(
    tmp_path: Path,
    data_dir: Path,
) -> None:
    existing_file = data_dir / "movies" / "tmdb-999.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Theme Movie",
                "year": 2020,
                "tmdb_id": 999,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": None,
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": "themerr1111",
            },
            indent=2,
        )
        + "\n"
    )

    body = f"""### Title

Theme Movie

### Year

2020

### TMDB ID

999

### YouTube theme video ID

overture111

### Reason for modification

{EMPTY_REASON}
"""
    parsed = parse_issue_form(body, "[Movie]: Theme Movie (2020)", ["movie"])
    res = process_contribution(parsed, tmp_path, dry_run=False)
    assert res["status"] == "ok"
    assert not res["is_modification"]
    assert res["is_addition"]
    assert "https://www.youtube.com/watch?v=overture111" in res["media_comparison"]
    assert res["youtube_id"] == "overture111"

    saved = json.loads(existing_file.read_text())
    assert saved["youtube_id_overturedb"] == "overture111"
    assert saved["youtube_id_themerrdb"] == "themerr1111"


def test_show_season_poster_replacement_vs_addition(
    tmp_path: Path, data_dir: Path
) -> None:
    show_file = data_dir / "shows" / "tvdb-600.json"
    show_file.write_text(
        json.dumps(
            {
                "media_type": "show",
                "title": "Season Show",
                "year": 2022,
                "tmdb_id": None,
                "tvdb_id": 600,
                "imdb_id": None,
                "poster_url": None,
                "background_url": None,
                "youtube_id_overturedb": None,
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

    # Replacing Season 1 poster without reason blocks
    body_replace = f"""### Title

Season Show

### TVDB ID

600

### Season posters

1=https://image.tmdb.org/t/p/original/s1_new.jpg

### Reason for modification

{EMPTY_REASON}
"""
    parsed = parse_issue_form(body_replace, "[Show]: Season Show", ["show"])
    with pytest.raises(ValueError) as ctx:
        process_contribution(parsed, tmp_path, dry_run=False)
    assert "needs a reason" in str(ctx.value)

    # Adding Season 2 poster without reason succeeds
    body_add = f"""### Title

Season Show

### TVDB ID

600

### Season posters

2=https://image.tmdb.org/t/p/original/s2.jpg

### Reason for modification

{EMPTY_REASON}
"""
    parsed_add = parse_issue_form(body_add, "[Show]: Season Show", ["show"])
    res = process_contribution(parsed_add, tmp_path, dry_run=False)
    assert not res["is_modification"]
    assert res["is_addition"]

    updated = json.loads(show_file.read_text())
    assert len(updated["seasons"]) == 2
    assert (
        updated["seasons"][0]["poster_url"]
        == "https://image.tmdb.org/t/p/original/s1.jpg"
    )
    assert (
        updated["seasons"][1]["poster_url"]
        == "https://image.tmdb.org/t/p/original/s2.jpg"
    )


def test_clean_art_url_markdown_links_and_formatting(subtests: pytest.Subtests) -> None:
    assert clean_art_url("   ") is None
    assert clean_art_url("_No response_") is None

    # Markdown link extraction
    md_link = "[Movie Poster](https://image.tmdb.org/t/p/original/test.jpg)"
    assert clean_art_url(md_link) == "https://image.tmdb.org/t/p/original/test.jpg"
    md_spaced = "[Poster](  https://image.tmdb.org/t/p/original/spaced.jpg  )"
    assert clean_art_url(md_spaced) == "https://image.tmdb.org/t/p/original/spaced.jpg"

    # Quotes and angle brackets
    assert (
        clean_art_url('"https://image.tmdb.org/t/p/original/quoted.jpg"')
        == "https://image.tmdb.org/t/p/original/quoted.jpg"
    )
    assert (
        clean_art_url("'https://image.tmdb.org/t/p/original/single.jpg'")
        == "https://image.tmdb.org/t/p/original/single.jpg"
    )
    assert (
        clean_art_url("<https://image.tmdb.org/t/p/original/angled.jpg>")
        == "https://image.tmdb.org/t/p/original/angled.jpg"
    )

    # HTTP upgrade
    assert (
        clean_art_url("http://image.tmdb.org/t/p/original/http.jpg")
        == "https://image.tmdb.org/t/p/original/http.jpg"
    )

    # Fragment stripping
    assert (
        clean_art_url("https://image.tmdb.org/t/p/original/frag.jpg#zoom=100")
        == "https://image.tmdb.org/t/p/original/frag.jpg"
    )

    # ThePosterDB conversions and cleaning
    assert (
        clean_art_url("https://theposterdb.com/poster/12345")
        == "https://theposterdb.com/api/assets/12345"
    )
    assert (
        clean_art_url("https://www.theposterdb.com/poster/12345/")
        == "https://theposterdb.com/api/assets/12345"
    )
    assert (
        clean_art_url("https://theposterdb.com/api/assets/12345/view")
        == "https://theposterdb.com/api/assets/12345"
    )
    assert (
        clean_art_url("https://theposterdb.com/api/assets/12345/view/")
        == "https://theposterdb.com/api/assets/12345"
    )
    assert (
        clean_art_url("https://theposterdb.com/api/assets/12345/")
        == "https://theposterdb.com/api/assets/12345"
    )

    # Resized and non-catalog links
    assert (
        clean_art_url("https://image.tmdb.org/t/p/w342/resized.jpg")
        == "https://image.tmdb.org/t/p/original/resized.jpg"
    )
    for url in (
        "https://theposterdb.com/set/12345",
        "https://example.com/poster.jpg",
    ):
        with subtests.test(url=url), pytest.raises(ValueError):
            clean_art_url(url)


def test_clean_youtube_id_all_variants_and_errors() -> None:
    assert clean_youtube_id(None) is None
    assert clean_youtube_id("") is None
    assert clean_youtube_id("   ") is None
    assert clean_youtube_id("_No response_") is None

    # Raw 11-char ID
    assert clean_youtube_id("AB96CvvLZKc") == "AB96CvvLZKc"
    assert clean_youtube_id('"AB96CvvLZKc"') == "AB96CvvLZKc"
    assert clean_youtube_id("<AB96CvvLZKc>") == "AB96CvvLZKc"

    # Full URL variations
    assert (
        clean_youtube_id("https://www.youtube.com/watch?v=AB96CvvLZKc") == "AB96CvvLZKc"
    )
    assert clean_youtube_id("https://youtube.com/watch?v=AB96CvvLZKc") == "AB96CvvLZKc"
    assert (
        clean_youtube_id("https://m.youtube.com/watch?v=AB96CvvLZKc") == "AB96CvvLZKc"
    )
    assert (
        clean_youtube_id("https://music.youtube.com/watch?v=AB96CvvLZKc")
        == "AB96CvvLZKc"
    )
    assert clean_youtube_id("https://youtu.be/AB96CvvLZKc") == "AB96CvvLZKc"
    assert (
        clean_youtube_id("https://youtu.be/AB96CvvLZKc?si=xyz&t=15s") == "AB96CvvLZKc"
    )
    assert (
        clean_youtube_id("https://www.youtube.com/embed/AB96CvvLZKc") == "AB96CvvLZKc"
    )
    assert (
        clean_youtube_id("https://www.youtube.com/shorts/AB96CvvLZKc") == "AB96CvvLZKc"
    )
    assert (
        clean_youtube_id("https://www.youtube.com/watch?feature=shared&v=AB96CvvLZKc")
    ) == "AB96CvvLZKc"
    assert (
        clean_youtube_id("[Theme Song](https://youtu.be/AB96CvvLZKc)") == "AB96CvvLZKc"
    )

    # Invalid IDs or URLs
    with pytest.raises(ValueError):
        clean_youtube_id("short")
    with pytest.raises(ValueError):
        clean_youtube_id("https://vimeo.com/12345678901")
    with pytest.raises(ValueError):
        clean_youtube_id("https://youtube.com/watch")
    with pytest.raises(ValueError):
        clean_youtube_id("invalid!characters@#$")


def test_parse_external_ids_urls_and_casing() -> None:
    body = """### Title

Test

### TMDB ID

https://www.themoviedb.org/movie/157336-interstellar

### TVDB ID

https://thetvdb.com/dereferrer/series/74205

### IMDb ID

https://www.imdb.com/title/TT0109424/?ref_=fn_al_tt_1
"""
    parsed = parse_issue_form(body, "[Movie]: Test", ["movie"])
    assert parsed.tmdb_id == 157336
    assert parsed.tvdb_id == 74205
    assert parsed.imdb_id == "tt0109424"

    # Zero or negative IDs
    with pytest.raises(ValueError) as ctx:
        parse_issue_form("### Title\nT\n### TMDB ID\n0", "[Movie]: T", ["movie"])
    assert "positive integer" in str(ctx.value)

    with pytest.raises(ValueError) as ctx:
        parse_issue_form("### Title\nT\n### TVDB ID\n0", "[Show]: T", ["show"])
    assert "positive integer" in str(ctx.value)

    # No IDs provided
    with pytest.raises(ValueError) as ctx:
        parse_issue_form("### Title\nT", "[Movie]: T", ["movie"])
    assert "need a TMDB, TVDB, or IMDb ID" in str(ctx.value)


def test_parse_seasons_complex_inputs() -> None:
    body = """### Title

Show

### TVDB ID

123

### Season posters

- Season 1 = https://image.tmdb.org/t/p/original/s1.jpg
* s2 = https://image.tmdb.org/t/p/original/s2.jpg
1. Season Specials = https://image.tmdb.org/t/p/original/s0.jpg
"""
    parsed = parse_issue_form(body, "[Show]: Show", ["show"])
    assert len(parsed.seasons) == 3
    assert parsed.seasons == [
        {
            "season_num": 1,
            "poster_url": "https://image.tmdb.org/t/p/original/s1.jpg",
        },
        {
            "season_num": 2,
            "poster_url": "https://image.tmdb.org/t/p/original/s2.jpg",
        },
        {
            "season_num": 0,
            "poster_url": "https://image.tmdb.org/t/p/original/s0.jpg",
        },
    ]

    # Duplicate seasons
    dup_body = (
        "### Title\nShow\n### TVDB ID\n123\n"
        "### Season posters\n1=https://image.tmdb.org/t/p/original/a.jpg\n"
        "Season 1=https://image.tmdb.org/t/p/original/b.jpg"
    )
    with pytest.raises(ValueError) as ctx:
        parse_issue_form(dup_body, "[Show]: Show", ["show"])
    assert "Duplicate season number in submission: 1" in str(ctx.value)

    # Missing '='
    bad_format_body = (
        "### Title\nShow\n### TVDB ID\n123\n"
        "### Season posters\nSeason 1 https://image.tmdb.org/t/p/original/a.jpg"
    )
    with pytest.raises(ValueError) as ctx:
        parse_issue_form(bad_format_body, "[Show]: Show", ["show"])
    assert "must use format season_num=url" in str(ctx.value)

    # Season posters on movie
    movie_with_seasons = (
        "### Title\nMovie\n### TMDB ID\n123\n"
        "### Season posters\n1=https://image.tmdb.org/t/p/original/a.jpg"
    )
    with pytest.raises(ValueError) as ctx:
        parse_issue_form(movie_with_seasons, "[Movie]: Movie", ["movie"])
    assert "Season posters cannot be added to a movie" in str(ctx.value)


def test_modification_reason_validations(tmp_path: Path, data_dir: Path) -> None:
    existing_file = data_dir / "movies" / "tmdb-55555.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Movie",
                "year": 2024,
                "tmdb_id": 55555,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": "https://image.tmdb.org/t/p/original/old.jpg",
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": None,
            },
            indent=2,
        )
        + "\n"
    )

    invalid_reasons = [
        "   ",
        '""',
        "_No response_",
        "none",
        "N/A",
    ]

    for invalid_reason in invalid_reasons:
        body = f"""### Title

Movie

### TMDB ID

55555

### Poster URL

https://image.tmdb.org/t/p/original/new.jpg

### Reason for modification

{invalid_reason}
"""
        parsed = parse_issue_form(body, "[Movie]: Movie (2024)", ["movie"])
        with pytest.raises(ValueError) as ctx:
            process_contribution(parsed, tmp_path, dry_run=False)
        assert "needs a reason" in str(ctx.value)


def test_empty_diff_on_existing_entry_rejected(tmp_path: Path, data_dir: Path) -> None:
    existing_file = data_dir / "movies" / "tmdb-66666.json"
    existing_file.write_text(
        json.dumps(
            {
                "media_type": "movie",
                "title": "Unchanged Movie",
                "year": 2024,
                "tmdb_id": 66666,
                "tvdb_id": None,
                "imdb_id": None,
                "poster_url": "https://image.tmdb.org/t/p/original/p.jpg",
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": "themerr1234",
            },
            indent=2,
        )
        + "\n"
    )

    # Identical submission
    body_identical = """### Title

Unchanged Movie

### Year

2024

### TMDB ID

66666

### Poster URL

https://image.tmdb.org/t/p/original/p.jpg
"""
    parsed = parse_issue_form(
        body_identical, "[Movie]: Unchanged Movie (2024)", ["movie"]
    )
    with pytest.raises(ValueError) as ctx:
        process_contribution(parsed, tmp_path, dry_run=False)
    assert "No changes or additions detected" in str(ctx.value)

    # Submitting only matching themerrdb theme with no art changes
    body_themerr_only = """### Title

Unchanged Movie

### Year

2024

### TMDB ID

66666

### YouTube theme video ID

themerr1234
"""
    parsed_yt = parse_issue_form(
        body_themerr_only, "[Movie]: Unchanged Movie (2024)", ["movie"]
    )
    with pytest.raises(ValueError) as ctx:
        process_contribution(parsed_yt, tmp_path, dry_run=False)
    assert "already active via ThemerrDB" in str(ctx.value)


def test_field_leading_empty_lines_tolerated() -> None:
    body = """### Title


Spaced Movie

### Year


2024

### TMDB ID


123456

### Poster URL


https://image.tmdb.org/t/p/original/spaced_poster.jpg

### YouTube theme video ID


AB96CvvLZKc
"""
    parsed = parse_issue_form(body, "[Movie]: Spaced Movie (2024)", ["movie"])
    assert parsed.title == "Spaced Movie"
    assert parsed.year == 2024
    assert parsed.tmdb_id == 123456
    assert parsed.poster_url == "https://image.tmdb.org/t/p/original/spaced_poster.jpg"
    assert parsed.youtube_id == "AB96CvvLZKc"
