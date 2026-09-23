"""Statistics distinguish selected assets from covered titles."""

import unittest
from xml.etree import ElementTree

from catalog_stats import dashboard, statistics_json, summarize
from test_catalog import movie


class StatisticsTests(unittest.TestCase):
    def test_totals_count_both_theme_sources_and_shared_assets(self) -> None:
        entries = [
            movie(
                background_url="https://image.tmdb.org/background.jpg",
                youtube_id_overturedb="aaaaaaaaaaa",
                youtube_id_themerrdb="bbbbbbbbbbb",
            ),
            movie(tmdb_id=2, youtube_id_themerrdb="bbbbbbbbbbb"),
            movie(
                media_type="show",
                poster_url=None,
                youtube_id_overturedb="ccccccccccc",
                seasons=[
                    {"season_num": 0, "poster_url": "https://image.tmdb.org/s.jpg"},
                    {"season_num": 1, "poster_url": "https://image.tmdb.org/s.jpg"},
                ],
            ),
            movie(media_type="show", tmdb_id=2, poster_url=None, seasons=[]),
        ]
        counts = summarize(entries)
        self.assertEqual(counts["movies"].titles, 2)
        self.assertEqual(counts["shows"].titles, 2)
        total = counts["total"]
        self.assertEqual(total.titles, 4)
        self.assertEqual(total.posters, 2)
        self.assertEqual(total.backgrounds, 1)
        self.assertEqual(total.season_posters, 2)
        self.assertEqual(total.shows_with_season_posters, 1)
        self.assertEqual(total.themes, 4)
        self.assertEqual(total.overturedb_themes, 2)
        self.assertEqual(total.themerrdb_themes, 2)
        self.assertEqual(total.titles_with_themes, 3)
        self.assertEqual(total.core_complete, 1)
        self.assertEqual(counts["shows"].core_complete, 0)

    def test_empty_catalog_has_no_undefined_or_misleading_percentages(self) -> None:
        counts = summarize([])
        for dark in (False, True):
            svg = dashboard(
                counts, revision="a" * 40, generated_at="2026-09-22", dark=dark
            )
            ElementTree.fromstring(svg)  # noqa: S314 - locally generated SVG
            self.assertIn("0 / 0 · n/a", svg)
            self.assertNotIn("100.0%", svg)

    def test_json_preserves_provenance_and_svg_escapes_text(self) -> None:
        counts = summarize([movie()])
        revision, generated_at = "abc<>&123", "2026-09-22T00:00:00Z"
        payload = statistics_json(counts, revision=revision, generated_at=generated_at)
        self.assertEqual(payload["source_revision"], revision)
        self.assertEqual(payload["generated_at"], generated_at)
        self.assertEqual(payload["counts"]["total"]["posters"], 1)
        for dark in (False, True):
            svg = dashboard(
                counts, revision=revision, generated_at=generated_at, dark=dark
            )
            parsed = ElementTree.fromstring(svg)  # noqa: S314 - locally generated SVG
            self.assertIn("1 / 1 · 100.0%", "".join(parsed.itertext()))
            self.assertIn(revision[:7], "".join(parsed.itertext()))


if __name__ == "__main__":
    unittest.main()
