"""Statistics distinguish selected assets from covered titles."""

lazy from xml.etree import ElementTree

lazy from scripts.catalog_stats import dashboard, statistics_json, summarize
lazy from tests.test_catalog import collection, movie


def test_totals_count_both_theme_sources_and_shared_assets() -> None:
    entries = [
        movie(
            background_url="https://image.tmdb.org/t/p/original/background.jpg",
            youtube_id_overturedb="aaaaaaaaaaa",
            youtube_id_themerrdb="bbbbbbbbbbb",
        ),
        movie(tmdb_id=2, youtube_id_themerrdb="bbbbbbbbbbb"),
        movie(
            media_type="show",
            poster_url=None,
            youtube_id_overturedb="ccccccccccc",
            seasons=[
                {
                    "season_num": 0,
                    "poster_url": "https://image.tmdb.org/t/p/original/s.jpg",
                },
                {
                    "season_num": 1,
                    "poster_url": "https://image.tmdb.org/t/p/original/s.jpg",
                },
            ],
        ),
        movie(media_type="show", tmdb_id=2, poster_url=None, seasons=[]),
        collection(),
    ]
    counts = summarize(entries)
    assert counts["movies"].titles == 2
    assert counts["shows"].titles == 2
    assert counts["collections"].titles == 1
    assert counts["collections"].titles_with_themes == 1
    total = counts["total"]
    assert total.titles == 5
    assert total.posters == 2
    assert total.backgrounds == 1
    assert total.season_posters == 2
    assert total.shows_with_season_posters == 1
    assert total.themes == 5
    assert total.overturedb_themes == 2
    assert total.themerrdb_themes == 3
    assert total.titles_with_themes == 4
    assert total.core_complete == 1
    assert counts["shows"].core_complete == 0


def test_empty_catalog_has_no_undefined_or_misleading_percentages() -> None:
    counts = summarize([])
    for dark in (False, True):
        svg = dashboard(counts, revision="a" * 40, generated_at="2026-09-22", dark=dark)
        ElementTree.fromstring(svg)  # noqa: S314 - locally generated SVG
        assert "0 / 0 · n/a" in svg
        assert "100.0%" not in svg


def test_json_preserves_provenance_and_svg_escapes_text() -> None:
    counts = summarize([movie()])
    revision, generated_at = "abc<>&123", "2026-09-22T00:00:00Z"
    payload = statistics_json(counts, revision=revision, generated_at=generated_at)
    assert payload["source_revision"] == revision
    assert payload["generated_at"] == generated_at
    assert payload["counts"]["total"]["posters"] == 1
    for dark in (False, True):
        svg = dashboard(counts, revision=revision, generated_at=generated_at, dark=dark)
        parsed = ElementTree.fromstring(svg)  # noqa: S314 - locally generated SVG
        assert "1 / 1 · 100.0%" in "".join(parsed.itertext())
        assert revision[:7] in "".join(parsed.itertext())


def test_titles_flagged_without_a_theme_count_as_themed() -> None:
    total = summarize([movie(no_theme=True)])["total"]
    assert (total.themes, total.titles_with_themes) == (0, 1)
