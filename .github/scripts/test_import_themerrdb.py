"""Unit tests for the ThemerrDB import script."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import import_themerrdb as importer
from contract import validate_entry
from test_catalog import movie


class ImportThemerrdbTests(unittest.TestCase):
    def test_extract_youtube_id(self):
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
            with self.subTest(input_val=input_val):
                self.assertEqual(importer.extract_youtube_id(input_val), expected)

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
            with self.subTest(input_val=input_val):
                self.assertIsNone(importer.extract_youtube_id(input_val))

    def test_parse_year(self):
        self.assertEqual(importer.parse_year("2014-10-10"), 2014)
        self.assertEqual(importer.parse_year("1995"), 1995)
        self.assertIsNone(importer.parse_year(None))
        self.assertIsNone(importer.parse_year(""))
        self.assertIsNone(importer.parse_year("0999-01-01"))
        self.assertIsNone(importer.parse_year("not-a-date"))

    def test_process_themerr_item_updates_existing_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
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
                "youtube_id": "original_yt",
                "youtube_id_secondary": None,
            }
            existing_file.write_text(json.dumps(existing_data), encoding="utf-8")

            by_tmdb, by_imdb, loaded = importer.index_existing_entries(data_dir)

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
                by_tmdb,
                by_imdb,
                loaded,
                data_dir,
                dry_run=False,
            )

            self.assertEqual(status, "updated")

            updated_data = json.loads(existing_file.read_text(encoding="utf-8"))
            self.assertEqual(updated_data["youtube_id"], "original_yt")
            self.assertEqual(updated_data["youtube_id_secondary"], "themerr_sec")
            # Must NOT touch imdb_id or poster_url
            self.assertIsNone(updated_data["imdb_id"])
            self.assertEqual(
                updated_data["poster_url"],
                "https://image.tmdb.org/t/p/original/curated.jpg",
            )
            validate_entry(updated_data)

    def test_process_themerr_item_adds_new_movie(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir(parents=True)

            by_tmdb, by_imdb, loaded = importer.index_existing_entries(data_dir)

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
                by_tmdb,
                by_imdb,
                loaded,
                data_dir,
                dry_run=False,
            )

            self.assertEqual(status, "added")

            target_file = data_dir / "movies" / "tmdb-99999.json"
            self.assertTrue(target_file.exists())

            saved = json.loads(target_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["media_type"], "movie")
            self.assertEqual(saved["title"], "New Film")
            self.assertEqual(saved["year"], 2023)
            self.assertEqual(saved["tmdb_id"], 99999)
            self.assertIsNone(saved["youtube_id"])
            self.assertEqual(saved["youtube_id_secondary"], "newfilmthem")
            self.assertIsNone(saved["imdb_id"])
            self.assertIsNone(saved["tvdb_id"])
            self.assertIsNone(saved["poster_url"])
            self.assertIsNone(saved["background_url"])
            validate_entry(saved)

    def test_process_themerr_item_adds_new_show_with_empty_seasons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir(parents=True)

            by_tmdb, by_imdb, loaded = importer.index_existing_entries(data_dir)

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
                by_tmdb,
                by_imdb,
                loaded,
                data_dir,
                dry_run=False,
            )

            self.assertEqual(status, "added")

            target_file = data_dir / "shows" / "tmdb-88888.json"
            self.assertTrue(target_file.exists())

            saved = json.loads(target_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["media_type"], "show")
            self.assertEqual(saved["title"], "New Anime Show")
            self.assertEqual(saved["year"], 2021)
            self.assertEqual(saved["youtube_id_secondary"], "anime_theme")
            self.assertIsNone(saved["youtube_id"])
            self.assertIsNone(saved["poster_url"])
            self.assertIsNone(saved["background_url"])
            self.assertIsNone(saved["imdb_id"])
            self.assertIsNone(saved["tvdb_id"])
            self.assertEqual(saved["seasons"], [])
            validate_entry(saved)

    def test_process_themerr_item_skips_when_no_theme_or_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir(parents=True)

            by_tmdb, by_imdb, loaded = importer.index_existing_entries(data_dir)

            self.assertEqual(
                importer.process_themerr_item(
                    {"id": 123, "youtube_theme_url": None},
                    "movie",
                    by_tmdb,
                    by_imdb,
                    loaded,
                    data_dir,
                ),
                "skipped_no_theme",
            )

            self.assertEqual(
                importer.process_themerr_item(
                    {"id": "not_an_int", "youtube_theme_url": "4xdyx5NVUhI"},
                    "movie",
                    by_tmdb,
                    by_imdb,
                    loaded,
                    data_dir,
                ),
                "skipped_invalid",
            )


class ImportIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = self.root / "data"
        self.movies = self.data / "movies"
        self.movies.mkdir(parents=True)
        self.upstream = self.root / "upstream"
        self.upstream_movies = self.upstream / "movies" / "themoviedb"
        self.upstream_shows = self.upstream / "tv_shows" / "themoviedb"
        self.upstream_movies.mkdir(parents=True)
        self.upstream_shows.mkdir(parents=True)
        self.record = {
            "id": 1,
            "title": "Imported movie",
            "youtube_theme_url": "https://youtu.be/4xdyx5NVUhI",
        }

    def write_existing(self, name="tmdb-1.json", **changes):
        path = self.movies / name
        path.write_text(json.dumps(movie(**changes)), encoding="utf-8")
        return path

    def write_upstream(self, name="1.json", **changes):
        path = self.upstream_movies / name
        path.write_text(json.dumps({**self.record, **changes}), encoding="utf-8")
        return path

    def run_import(self, **kwargs):
        return importer.import_themerrdb(self.upstream, self.root, **kwargs)

    def test_boolean_id_cannot_update_numeric_identity(self):
        path = self.write_existing()
        before = path.read_bytes()
        self.write_upstream(id=True)
        stats = self.run_import()
        self.assertEqual(stats["skipped_invalid"], 1)
        self.assertEqual(path.read_bytes(), before)

    def test_conflicting_identifiers_leave_curated_records_unchanged(self):
        first = self.write_existing(imdb_id="tt1")
        second = self.write_existing("tmdb-2.json", tmdb_id=2, imdb_id="tt2")
        before = [path.read_bytes() for path in (first, second)]
        for changes in (
            {"imdb_id": "tt2"},
            {"id": 3, "imdb_id": "tt1"},
            {"imdb_id": "tt3"},
        ):
            with self.subTest(changes=changes):
                self.write_upstream(**changes)
                with patch("sys.stderr", new=io.StringIO()):
                    self.assertEqual(self.run_import()["skipped_error"], 1)
                self.assertEqual(
                    [path.read_bytes() for path in (first, second)], before
                )

    def test_imdb_only_match_preserves_identity_and_existing_sources(self):
        prior_source = {
            "name": "Curator",
            "url": "https://example.org/entry",
            "license": "CC0-1.0",
        }
        path = self.write_existing(
            "imdb-tt1.json", tmdb_id=None, imdb_id="tt1", sources=[prior_source]
        )
        self.write_upstream(imdb_id="tt1")
        self.assertEqual(self.run_import()["updated"], 1)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsNone(saved["tmdb_id"])
        self.assertEqual(saved["youtube_id_secondary"], "4xdyx5NVUhI")
        self.assertEqual(saved["sources"], [prior_source])
        before = path.read_bytes()
        self.assertEqual(self.run_import()["skipped_unchanged"], 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(list(self.data.rglob("*.json"))), 1)

    def test_existing_matching_theme_is_skipped_unchanged(self):
        path = self.write_existing(youtube_id_secondary="4xdyx5NVUhI")
        self.write_upstream()
        self.assertEqual(self.run_import()["skipped_unchanged"], 1)
        self.assertNotIn("sources", json.loads(path.read_text()))

    def test_dry_run_and_real_import_agree_for_repeated_new_records(self):
        self.write_upstream()
        self.write_upstream("duplicate.json")
        planned = self.run_import(dry_run=True)
        self.assertFalse(list(self.data.rglob("*.json")))
        self.assertEqual(planned["added"], 1)
        self.assertEqual(planned["skipped_unchanged"], 1)
        self.assertEqual(self.run_import(), planned)

    def test_dry_run_never_changes_existing_file(self):
        path = self.write_existing()
        before = path.read_bytes()
        self.write_upstream()
        self.assertEqual(self.run_import(dry_run=True)["updated"], 1)
        self.assertEqual(path.read_bytes(), before)

    def test_missing_source_folder_fails_before_any_updates(self):
        path = self.write_existing()
        before = path.read_bytes()
        self.write_upstream()
        self.upstream_shows.rmdir()
        with self.assertRaisesRegex(ValueError, "directory does not exist"):
            self.run_import()
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_existing_file_is_never_overwritten(self):
        path = self.movies / "tmdb-1.json"
        path.write_text("{broken", encoding="utf-8")
        self.write_upstream()
        with self.assertRaises(ValueError):
            self.run_import()
        self.assertEqual(path.read_text(), "{broken")

    def test_duplicate_existing_identities_fail_before_writing(self):
        first = self.write_existing()
        self.write_existing("imdb-tt1.json", imdb_id="tt1")
        before = first.read_bytes()
        self.write_upstream()
        with self.assertRaisesRegex(ValueError, "Duplicate dataset identity"):
            self.run_import()
        self.assertEqual(first.read_bytes(), before)

    def test_malformed_records_are_reported_and_other_records_are_processed(self):
        self.write_upstream()
        (self.upstream_movies / "bad.json").write_text("[]", encoding="utf-8")
        (self.upstream_movies / "broken.json").write_text("{broken", encoding="utf-8")
        with patch("sys.stderr", new=io.StringIO()):
            stats = self.run_import()
        self.assertEqual(stats["skipped_error"], 2)
        self.assertEqual(stats["added"], 1)

    def test_limit_is_positive_and_applies_across_media_types(self):
        self.write_upstream()
        (self.upstream_shows / "1.json").write_text(
            json.dumps({**self.record, "name": "Imported show"}), encoding="utf-8"
        )
        for limit in (0, -1):
            with self.assertRaisesRegex(ValueError, "positive integer"):
                self.run_import(limit=limit)
        self.assertEqual(self.run_import(limit=1)["scanned"], 1)
        self.assertFalse((self.data / "shows").exists())
        self.assertEqual(self.run_import()["added"], 1)
        self.assertTrue((self.data / "shows" / "tmdb-1.json").exists())

    def test_cli_reports_missing_input_as_failure(self):
        with (
            patch(
                "sys.argv",
                ["import_themerrdb.py", "--themerr-dir", str(self.root / "missing")],
            ),
            patch("sys.stdout", new=io.StringIO()),
            patch("sys.stderr", new=io.StringIO()),
        ):
            self.assertEqual(importer.main(), 1)


if __name__ == "__main__":
    unittest.main()
