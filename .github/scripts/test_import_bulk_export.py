"""Tests for bulk export import engine enforcing Rule 1 & Rule 2."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

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
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_rule_1_preserves_existing_artwork_and_theme(self) -> None:
        existing = {
            "media_type": "movie",
            "title": "Movie",
            "year": 2020,
            "tmdb_id": 1,
            "tvdb_id": None,
            "imdb_id": None,
            "poster_url": "https://img.test/existing_poster.jpg",
            "background_url": "https://img.test/existing_bg.jpg",
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
            "poster_url": "https://img.test/new_poster.jpg",
            "background_url": "https://img.test/new_bg.jpg",
            "youtube_id_overturedb": "new11111111",
            "youtube_id_themerrdb": None,
        }
        updated, changed, _changes = merge_entry(existing, incoming)
        self.assertFalse(changed)
        self.assertEqual(updated["poster_url"], "https://img.test/existing_poster.jpg")
        self.assertEqual(updated["background_url"], "https://img.test/existing_bg.jpg")
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
            "poster_url": "https://img.test/new_poster.jpg",
            "background_url": "https://img.test/new_bg.jpg",
            "youtube_id_overturedb": "new11111111",
            "youtube_id_themerrdb": None,
        }
        updated, changed, changes = merge_entry(existing, incoming)
        self.assertTrue(changed)
        self.assertEqual(updated["poster_url"], "https://img.test/new_poster.jpg")
        self.assertEqual(updated["background_url"], "https://img.test/new_bg.jpg")
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
                {"season_num": 1, "poster_url": "https://img.test/season1_exist.jpg"}
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
                {"season_num": 1, "poster_url": "https://img.test/season1_new.jpg"},
                {"season_num": 2, "poster_url": "https://img.test/season2_new.jpg"},
            ],
        }
        updated, changed, _changes = merge_entry(existing, incoming)
        self.assertTrue(changed)
        self.assertEqual(len(updated["seasons"]), 2)
        # Season 1 preserved:
        self.assertEqual(
            updated["seasons"][0]["poster_url"], "https://img.test/season1_exist.jpg"
        )
        # Season 2 added:
        self.assertEqual(
            updated["seasons"][1]["poster_url"], "https://img.test/season2_new.jpg"
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
            "poster_url": "https://img.test/p.jpg",
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
            "poster_url": "https://img.test/p.jpg",
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
                    "poster_url": "https://img.test/show_poster.jpg",
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
                    "poster_url": "https://img.test/ignored_new_poster.jpg",
                    "background_url": "https://img.test/new_bg.jpg",
                    "youtube_id_overturedb": "showtheme11",
                    "youtube_id_themerrdb": None,
                    "seasons": [
                        {"season_num": 1, "poster_url": "https://img.test/s1.jpg"}
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
        self.assertEqual(final_show["poster_url"], "https://img.test/show_poster.jpg")
        self.assertEqual(final_show["background_url"], "https://img.test/new_bg.jpg")
        self.assertEqual(final_show["youtube_id_overturedb"], "showtheme11")
        self.assertEqual(len(final_show["seasons"]), 1)

    def test_rejection_over_1000_entries_archive(self) -> None:
        import zipfile

        zip_path = self.temp_dir / "too_many.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for i in range(1001):
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

    def test_rejection_over_1000_entries_directory(self) -> None:
        large_dir = self.temp_dir / "large_dir"
        large_dir.mkdir()
        for i in range(1001):
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


if __name__ == "__main__":
    unittest.main()
