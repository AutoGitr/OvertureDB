"""Tests for bulk export import engine enforcing Rule 1 & Rule 2."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from import_bulk_export import (
    create_new_entry,
    import_bulk_export,
    merge_entry,
)


class BulkImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.data_dir = self.temp_dir / "data"
        (self.data_dir / "movies").mkdir(parents=True)
        (self.data_dir / "shows").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir)

    def test_rule_1_preserves_existing_artwork_and_theme(self) -> None:
        existing = {
            "media_type": "movie",
            "title": "Movie",
            "year": 2020,
            "tmdb_id": 1,
            "tvdb_id": None,
            "imdb_id": None,
            "poster_url": "https://image.tmdb.org/existing_poster.jpg",
            "background_url": "https://image.tmdb.org/existing_bg.jpg",
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
            "poster_url": "https://image.tmdb.org/new_poster.jpg",
            "background_url": "https://image.tmdb.org/new_bg.jpg",
            "youtube_id_overturedb": "new11111111",
            "youtube_id_themerrdb": None,
        }
        updated, changed, _changes = merge_entry(existing, incoming)
        self.assertFalse(changed)
        self.assertEqual(
            updated["poster_url"], "https://image.tmdb.org/existing_poster.jpg"
        )
        self.assertEqual(
            updated["background_url"], "https://image.tmdb.org/existing_bg.jpg"
        )
        self.assertEqual(updated["youtube_id_overturedb"], "existing111")

    def test_rule_1_backfills_missing_artwork_and_theme(self) -> None:
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
            "poster_url": "https://image.tmdb.org/new_poster.jpg",
            "background_url": "https://image.tmdb.org/new_bg.jpg",
            "youtube_id_overturedb": "new11111111",
            "youtube_id_themerrdb": None,
        }
        updated, changed, changes = merge_entry(existing, incoming)
        self.assertTrue(changed)
        self.assertEqual(updated["poster_url"], "https://image.tmdb.org/new_poster.jpg")
        self.assertEqual(updated["background_url"], "https://image.tmdb.org/new_bg.jpg")
        self.assertEqual(updated["youtube_id_overturedb"], "new11111111")
        self.assertIn("backfilled poster_url", changes)
        self.assertIn("backfilled background_url", changes)
        self.assertIn("backfilled youtube_id_overturedb", changes)

    def test_rule_1_shows_preserves_existing_seasons_and_adds_missing(self) -> None:
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
                    "poster_url": "https://image.tmdb.org/season1_exist.jpg",
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
                    "poster_url": "https://image.tmdb.org/season1_new.jpg",
                },
                {
                    "season_num": 2,
                    "poster_url": "https://image.tmdb.org/season2_new.jpg",
                },
            ],
        }
        updated, changed, _changes = merge_entry(existing, incoming)
        self.assertTrue(changed)
        self.assertEqual(len(updated["seasons"]), 2)
        # Season 1 preserved:
        self.assertEqual(
            updated["seasons"][0]["poster_url"],
            "https://image.tmdb.org/season1_exist.jpg",
        )
        # Season 2 added:
        self.assertEqual(
            updated["seasons"][1]["poster_url"],
            "https://image.tmdb.org/season2_new.jpg",
        )

    def test_rule_2_preserves_youtube_id_themerrdb(self) -> None:
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
            "poster_url": "https://image.tmdb.org/p.jpg",
            "background_url": None,
            "youtube_id_overturedb": "primary1111",
            "youtube_id_themerrdb": None,
        }
        updated, changed, _changes = merge_entry(existing, incoming)
        self.assertTrue(changed)
        self.assertEqual(updated["youtube_id_themerrdb"], "secondary11")
        self.assertEqual(updated["youtube_id_overturedb"], "primary1111")

    def test_rule_2_new_entry_has_null_themerrdb_theme(self) -> None:
        incoming = {
            "media_type": "movie",
            "title": "Brand New Movie",
            "year": 2021,
            "tmdb_id": 999,
            "tvdb_id": None,
            "imdb_id": None,
            "poster_url": "https://image.tmdb.org/p.jpg",
            "background_url": None,
            "youtube_id_overturedb": "primary1111",
            "youtube_id_themerrdb": "should_be_ignored",
        }
        path, entry = create_new_entry(incoming, self.data_dir)
        self.assertEqual(path.name, "tmdb-999.json")
        self.assertIsNone(entry["youtube_id_themerrdb"])

    def test_conflicting_youtube_id_skips_backfill_overturedb(self) -> None:
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
        self.assertFalse(changed)
        self.assertIsNone(updated["youtube_id_overturedb"])
        self.assertEqual(updated["youtube_id_themerrdb"], "conflict111")

    def test_rejects_conflicting_external_ids(self) -> None:
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
        with self.assertRaises(ValueError):
            merge_entry(existing, incoming)

    def test_end_to_end_cross_provider_matching(self) -> None:
        # Existing show under tvdb prefix
        show_path = self.data_dir / "shows" / "tvdb-200.json"
        show_path.write_text(
            json.dumps(
                {
                    "media_type": "show",
                    "title": "My Show",
                    "year": 2020,
                    "tmdb_id": 100,
                    "tvdb_id": 200,
                    "imdb_id": None,
                    "poster_url": "https://image.tmdb.org/show_poster.jpg",
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
        input_dir = self.temp_dir / "export"
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
                    "poster_url": "https://image.tmdb.org/ignored_new_poster.jpg",
                    "background_url": "https://image.tmdb.org/new_bg.jpg",
                    "youtube_id_overturedb": "showtheme11",
                    "youtube_id_themerrdb": None,
                    "seasons": [
                        {"season_num": 1, "poster_url": "https://image.tmdb.org/s1.jpg"}
                    ],
                },
                indent=2,
            )
            + "\n"
        )

        res = import_bulk_export(
            overture_dir=self.temp_dir, input_dir=input_dir, dry_run=False
        )
        self.assertEqual(res["created"], 0)
        self.assertEqual(res["backfilled"], 1)
        self.assertEqual(res["skipped"], 0)

        # Assert no duplicate tmdb-100.json was created in data/shows
        self.assertFalse((self.data_dir / "shows" / "tmdb-100.json").exists())

        # Assert tvdb-200.json was updated in place with Rule 1 applied
        final_show = json.loads(show_path.read_text())
        self.assertEqual(
            final_show["poster_url"], "https://image.tmdb.org/show_poster.jpg"
        )
        self.assertEqual(
            final_show["background_url"], "https://image.tmdb.org/new_bg.jpg"
        )
        self.assertEqual(final_show["youtube_id_overturedb"], "showtheme11")
        self.assertEqual(len(final_show["seasons"]), 1)

    @mock.patch("import_bulk_export.MAX_ARCHIVE_ENTRIES", 5)
    def test_rejection_over_max_entries_archive(self) -> None:
        import zipfile

        zip_path = self.temp_dir / "too_many.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i in range(6):
                zf.writestr(f"movie_{i}.json", "{}")
        with self.assertRaises(ValueError) as ctx:
            import_bulk_export(overture_dir=self.temp_dir, archive_path=zip_path)
        self.assertIn("exceeds maximum allowed entries", str(ctx.exception))

    def test_rejection_over_1mb_file_archive(self) -> None:
        import zipfile

        zip_path = self.temp_dir / "too_large_entry.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("large.json", " " * (1024 * 1024 + 1))
        with self.assertRaises(ValueError) as ctx:
            import_bulk_export(overture_dir=self.temp_dir, archive_path=zip_path)
        self.assertIn("exceeds maximum size", str(ctx.exception))

    @mock.patch("import_bulk_export.MAX_ARCHIVE_ENTRIES", 5)
    def test_rejection_over_max_entries_directory(self) -> None:
        large_dir = self.temp_dir / "large_dir"
        large_dir.mkdir()
        for i in range(6):
            (large_dir / f"entry_{i}.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            import_bulk_export(overture_dir=self.temp_dir, input_dir=large_dir)
        self.assertIn("exceeds maximum allowed entries", str(ctx.exception))

    def test_rejection_over_1mb_file_directory(self) -> None:
        large_dir = self.temp_dir / "large_file_dir"
        large_dir.mkdir()
        (large_dir / "huge.json").write_text(" " * (1024 * 1024 + 1), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            import_bulk_export(overture_dir=self.temp_dir, input_dir=large_dir)
        self.assertIn("exceeds maximum size", str(ctx.exception))

    def test_partial_import_writes_changes_and_reports_errors(self) -> None:
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
        input_dir = self.temp_dir / "mixed_input"
        input_dir.mkdir()
        (input_dir / "tmdb-999999.json").write_text(
            json.dumps(valid_entry), encoding="utf-8"
        )
        (input_dir / "tmdb-888888.json").write_text(
            json.dumps(invalid_entry), encoding="utf-8"
        )
        res = import_bulk_export(
            overture_dir=self.temp_dir, input_dir=input_dir, dry_run=False
        )
        self.assertEqual(res["created"], 1)
        self.assertEqual(len(res["errors"]), 1)
        self.assertTrue((self.data_dir / "movies" / "tmdb-999999.json").exists())
        self.assertFalse((self.data_dir / "movies" / "tmdb-888888.json").exists())

    def test_format_review_markdown_sorting_and_links(self) -> None:
        from import_bulk_export import ReviewItem, format_review_markdown

        items = [
            ReviewItem(
                title="Zoolander",
                year=2001,
                media_type="movie",
                poster_url="https://image.tmdb.org/zoolander.jpg",
                youtube_id="zoo12345678",
            ),
            ReviewItem(
                title="Avatar",
                year=2009,
                media_type="movie",
                background_url="https://image.tmdb.org/avatar_bg.jpg",
            ),
            ReviewItem(
                title="Breaking Bad",
                year=2008,
                media_type="show",
                seasons=[(1, "https://image.tmdb.org/bb_s1.jpg")],
            ),
        ]
        md = format_review_markdown(items)
        self.assertIn("<details>", md)
        self.assertIn(
            "<summary><b>Review Artwork & Theme URLs (3 items)</b></summary>", md
        )

        # Check alphabetical ordering: Avatar -> Breaking Bad -> Zoolander
        idx_avatar = md.index("Avatar (2009)")
        idx_bb = md.index("Breaking Bad (2008)")
        idx_zoolander = md.index("Zoolander (2001)")
        self.assertTrue(idx_avatar < idx_bb < idx_zoolander)

        # Check clickable links
        self.assertIn("[View image](<https://image.tmdb.org/avatar_bg.jpg>)", md)
        self.assertIn("[View image](<https://image.tmdb.org/zoolander.jpg>)", md)
        self.assertIn("[Watch video](https://www.youtube.com/watch?v=zoo12345678)", md)
        self.assertIn("[View image](<https://image.tmdb.org/bb_s1.jpg>)", md)

    def test_format_review_markdown_truncates_exceeding_max_chars(self) -> None:
        from import_bulk_export import ReviewItem, format_review_markdown

        items = [
            ReviewItem(
                title=f"Movie {i:03d}",
                year=2020,
                media_type="movie",
                poster_url=f"https://image.tmdb.org/poster_{i}.jpg",
            )
            for i in range(50)
        ]
        # Restrict max_chars to 500, which can fit only a couple items
        md = format_review_markdown(items, max_chars=500)
        self.assertIn("<details>", md)
        self.assertIn("Review Artwork & Theme URLs (50 items)", md)
        self.assertIn("Movie 000 (2020)", md)
        self.assertIn("more items (review full list in the PR diff).", md)
        self.assertLessEqual(len(md), 500)
        self.assertTrue(md.endswith("</details>"))


if __name__ == "__main__":
    unittest.main()
