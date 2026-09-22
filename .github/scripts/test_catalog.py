"""The publication contract and artifact guarantees, without network access."""

import gzip
import hashlib
import io
import json
import shutil
import socket
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.request import Request

import catalog
from contract import SCHEMA_VERSION, validate_catalog, validate_entries, validate_entry


def movie(**changes):
    return {
        "media_type": "movie",
        "title": "A Movie",
        "year": 2026,
        "tmdb_id": 1,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/movie.jpg",
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
        **changes,
    }


def envelope(entries):
    return {
        "schema_version": SCHEMA_VERSION,
        "source_revision": "a" * 40,
        "generated_at": "2026-09-04T12:00:00Z",
        "third_party_notices": "THIRD_PARTY_NOTICES.md",
        "entries": entries,
    }


class ContractTests(unittest.TestCase):
    def test_complete_repository_satisfies_contract(self):
        self.assertTrue(catalog.dataset())

    def test_entries_have_typed_identifiers_and_bounded_metadata(self):
        invalid = [
            {"title": " "},
            {"title": "x" * 201},
            {"year": 999},
            {"year": 10000},
            {"year": "2026"},
            {"year": 2026.0},
            {"tmdb_id": True},
            {"tmdb_id": 2**63},
            {"tmdb_id": 0},
            {"tmdb_id": -1},
            {"tmdb_id": None},
            {"imdb_id": "1234567"},
            {"media_type": "episode"},
            {"seasons": []},
            {"youtube_id_overturedb": "https://youtube.com/watch?v=abc"},
            {"youtube_id_themerrdb": "https://youtube.com/watch?v=abc"},
            {"youtube_id_overturedb": "3U6PSWyv5sc\n"},
            {"youtube_id_themerrdb": "3U6PSWyv5sc\n"},
            {"poster_url": "http://image.tmdb.org/a.jpg"},
            {"poster_url": "https://user:password@image.tmdb.org/a.jpg"},
            {"unrecognised": True},
        ]
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_entry(movie(**change))

    def test_valid_themerrdb_youtube_id(self):
        entry = movie(youtube_id_themerrdb="3U6PSWyv5sc")
        self.assertEqual(validate_entry(entry), entry)

    def test_youtube_ids_must_be_different(self):
        entry = movie(
            youtube_id_overturedb="3U6PSWyv5sc",
            youtube_id_themerrdb="3U6PSWyv5sc",
        )
        with self.assertRaises(ValueError):
            validate_entry(entry)

    def test_seasons_require_unique_nonnegative_numbers_and_posters(self):
        season = {"season_num": 0, "poster_url": "https://image.tmdb.org/s.jpg"}
        show = movie(media_type="show", seasons=[season])
        self.assertEqual(validate_entry(show), show)
        for seasons in (
            [season, {**season, "poster_url": "https://image.tmdb.org/other.jpg"}],
            [{**season, "season_num": -1}],
            [{"season_num": 1}],
        ):
            with self.subTest(seasons=seasons), self.assertRaises(ValueError):
                validate_entry({**show, "seasons": seasons})
        with self.assertRaises(ValueError):
            validate_entry(movie(media_type="show"))

    def test_identity_uniqueness_is_scoped_to_media_type(self):
        self.assertEqual(
            len(validate_entries([movie(), movie(media_type="show", seasons=[])])), 2
        )
        for field, value in (("tmdb_id", 1), ("tvdb_id", 10), ("imdb_id", "tt1234567")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_entries(
                    [movie(**{field: value}), movie(tmdb_id=2) | {field: value}]
                )

    def test_catalog_envelope_and_every_entry_are_validated(self):
        good = envelope([movie()])
        self.assertEqual(validate_catalog(good), [movie()])
        for change in (
            {"schema_version": 999},
            {"schema_version": True},
            {"generated_at": "2026-02-30T12:00:00Z"},
            {"generated_at": "2026-09-04"},
            {"source_revision": "unknown"},
            {"third_party_notices": "elsewhere"},
            {"entries": [movie(), movie(tmdb_id=2, year=False)]},
            {"entries": [movie(year=2026.0)]},
            {"entries": [movie(tmdb_id=1.0)]},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_catalog(good | change)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "data/movies").mkdir(parents=True)
        (self.root / "data/shows").mkdir()
        (self.root / "licenses").mkdir()
        (self.root / "licenses" / "THIRD_PARTY_NOTICES.md").write_text(
            "Notices\n", encoding="utf-8"
        )
        shutil.copytree(catalog.ROOT / "schema", self.root / "schema")
        self.entry = self.root / "data/movies/tmdb-1.json"
        self.entry.write_text(json.dumps(movie()), encoding="utf-8")

    def build(self, name):
        catalog.build(
            self.root / name,
            root=self.root,
            revision="a" * 40,
            generated_at="2026-09-04T12:00:00Z",
        )

    def test_publication_is_reproducible_and_digests_match(self):
        self.build("first")
        self.build("second")
        first, second = self.root / "first", self.root / "second"
        for path in first.rglob("*"):
            if path.is_file():
                self.assertEqual(
                    path.read_bytes(), (second / path.relative_to(first)).read_bytes()
                )
        raw = (first / "catalog.json").read_bytes()
        self.assertEqual(gzip.decompress((first / "catalog.json.gz").read_bytes()), raw)
        payload = json.loads(raw)
        self.assertEqual(payload, envelope([movie()]))
        validate_catalog(payload)
        for line in (first / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ")
            self.assertEqual(
                hashlib.sha256((first / name).read_bytes()).hexdigest(), digest
            )

    def test_invalid_entry_prevents_any_publication(self):
        bad = self.root / "data/movies/tmdb-2.json"
        bad.write_text(json.dumps(movie(tmdb_id=2, title="")), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.build("public")
        self.assertFalse((self.root / "public").exists())

    def test_filename_and_directory_follow_entry_identity(self):
        for destination in ("data/movies/tmdb-2.json", "data/shows/tmdb-1.json"):
            target = self.root / destination
            self.entry.rename(target)
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                catalog.dataset(self.root)
            target.rename(self.entry)

    def test_same_numeric_movie_and_show_id_have_separate_files(self):
        (self.root / "data/shows/tmdb-1.json").write_text(
            json.dumps(movie(media_type="show", seasons=[])), encoding="utf-8"
        )
        self.assertEqual(len(catalog.dataset(self.root)), 2)

    @patch.object(catalog, "build")
    @patch.object(
        catalog.subprocess, "check_output", return_value=" M data/movies/tmdb-1.json"
    )
    def test_cli_requires_source_to_match_its_revision(self, git_output, build):
        with (
            patch("sys.argv", ["catalog.py", "build"]),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(catalog.main(), 1)
        build.assert_not_called()
        git_output.assert_called_once()

    @patch.object(catalog, "build")
    @patch.object(catalog.subprocess, "check_output", side_effect=["", "a" * 40, "0"])
    def test_cli_uses_commit_metadata(self, git_output, build):
        with patch("sys.argv", ["catalog.py", "build"]):
            self.assertEqual(catalog.main(), 0)
        build.assert_called_once_with(
            catalog.ROOT / "public",
            revision="a" * 40,
            generated_at="1970-01-01T00:00:00Z",
        )

    @patch.object(catalog, "dataset")
    def test_cli_validate_entry_does_not_load_dataset(self, mock_dataset):
        with (
            patch.object(catalog, "ROOT", self.root),
            patch("sys.argv", ["catalog.py", "validate", "--entry", str(self.entry)]),
        ):
            self.assertEqual(catalog.main(), 0)
        mock_dataset.assert_not_called()

    def test_cli_validate_entry_rejects_invalid_path(self):
        outside = self.root / "tmdb-1.json"
        outside.write_text(self.entry.read_text(encoding="utf-8"), encoding="utf-8")
        for path in (outside, self.root / "nonexistent.json", self.entry.parent):
            with (
                self.subTest(path=path),
                patch.object(catalog, "ROOT", self.root),
                patch("sys.argv", ["catalog.py", "validate", "--entry", str(path)]),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                self.assertEqual(catalog.main(), 1)

    def test_cli_validate_entry_checks_filename_and_directory(self):
        for destination in ("data/movies/tmdb-2.json", "data/shows/tmdb-1.json"):
            target = self.root / destination
            self.entry.rename(target)
            with (
                self.subTest(destination=destination),
                patch.object(catalog, "ROOT", self.root),
                patch("sys.argv", ["catalog.py", "validate", "--entry", str(target)]),
                patch("sys.stderr", new_callable=io.StringIO),
            ):
                self.assertEqual(catalog.main(), 1)
            target.rename(self.entry)

    def test_cli_validate_entry_rejects_invalid_content(self):
        self.entry.write_text(json.dumps(movie(title="")), encoding="utf-8")
        with (
            patch.object(catalog, "ROOT", self.root),
            patch("sys.argv", ["catalog.py", "validate", "--entry", str(self.entry)]),
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(catalog.main(), 1)

    @patch.object(catalog, "check_art_url")
    def test_cli_validates_multiple_entries_and_checks_each_url_once(self, art):
        paths = [self.entry, self.root / "data/movies/tmdb-2.json"]
        for identifier, path in enumerate(paths, start=1):
            path.write_text(
                json.dumps(movie(tmdb_id=identifier)),
                encoding="utf-8",
            )
        with (
            patch.object(catalog, "ROOT", self.root),
            patch(
                "sys.argv",
                ["catalog.py", "validate", "--check-urls", "--entry", *map(str, paths)],
            ),
        ):
            self.assertEqual(catalog.main(), 0)
        art.assert_called_once_with(movie()["poster_url"])


class ArtworkTests(unittest.TestCase):
    @patch.object(
        socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    def test_destination_and_redirects_require_public_allowlisted_https(self, lookup):
        catalog.check_art_destination("https://image.tmdb.org/a.jpg")
        self.assertEqual(lookup.call_count, 1)
        for url in (
            "http://image.tmdb.org/a.jpg",
            "https://attacker.test/a.jpg",
            "https://image.tmdb.org:8443/a.jpg",
            "https://image.tmdb.org/a.svg",
            "https://theposterdb.com/poster/123",
            "https://theposterdb.com/api/assets/123/view",
            "https://theposterdb.com/api/assets/123/view/",
            "https://image.tmdb.org/a.jpg#fragment",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                catalog.check_art_destination(url)
        with self.assertRaises(ValueError):
            catalog.ArtRedirectHandler().redirect_request(
                Request("https://image.tmdb.org/a.jpg"),
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1/private",
            )
        lookup.return_value.append((2, 1, 6, "", ("127.0.0.1", 443)))
        with self.assertRaises(ValueError):
            catalog.check_art_destination("https://image.tmdb.org/a.jpg")

    @patch.object(catalog, "check_art_destination")
    @patch.object(catalog, "build_opener")
    def test_image_probe_reads_only_the_signature_and_checks_content(
        self, opener, destination
    ):
        response = MagicMock()
        response.headers = Message()
        response.headers["Content-Type"] = "image/jpeg"
        response.read.return_value = b"\xff\xd8\xff" + b"x" * 13
        opener.return_value.open.return_value.__enter__.return_value = response
        catalog.check_art_url("https://image.tmdb.org/a.jpg")
        response.read.assert_called_once_with(16)
        destination.assert_called_once()
        response.read.return_value = b"<html>Error"
        with self.assertRaises(ValueError):
            catalog.check_art_url("https://image.tmdb.org/a.jpg")

    def test_art_urls_are_deduplicated(self):
        entries = [movie(), movie(tmdb_id=2)]
        self.assertEqual(catalog.art_urls(entries), {movie()["poster_url"]})

    def test_parse_retry_after(self):
        self.assertEqual(catalog.parse_retry_after("10"), 10.0)
        self.assertEqual(catalog.parse_retry_after(None, default=3.0), 3.0)
        self.assertEqual(catalog.parse_retry_after("invalid", default=2.5), 2.5)

    @patch.object(catalog.time, "sleep")
    @patch.object(catalog, "check_art_destination")
    @patch.object(catalog, "build_opener")
    def test_image_probe_retries_on_http_429(self, opener, destination, mock_sleep):
        rate_error = catalog.HTTPError(
            "https://image.tmdb.org/a.jpg",
            429,
            "Too Many Requests",
            Message(),
            io.BytesIO(b""),
        )
        self.addCleanup(rate_error.close)
        rate_error.headers["Retry-After"] = "5"
        good_response = MagicMock()
        good_response.headers = Message()
        good_response.headers["Content-Type"] = "image/jpeg"
        good_response.read.return_value = b"\xff\xd8\xff" + b"x" * 13

        cm = MagicMock()
        cm.__enter__.return_value = good_response
        opener.return_value.open.side_effect = [rate_error, cm]

        catalog.check_art_url("https://image.tmdb.org/a.jpg")
        mock_sleep.assert_called_once_with(5.0)

    @patch.object(catalog.time, "sleep")
    @patch.object(catalog, "check_art_destination")
    @patch.object(catalog, "build_opener")
    def test_image_probe_exhausts_retries_on_http_429(
        self, opener, destination, mock_sleep
    ):
        rate_error = catalog.HTTPError(
            "https://image.tmdb.org/a.jpg",
            429,
            "Too Many Requests",
            Message(),
            io.BytesIO(b""),
        )
        self.addCleanup(rate_error.close)
        opener.return_value.open.side_effect = rate_error
        with self.assertRaises(catalog.HTTPError):
            catalog.check_art_url("https://image.tmdb.org/a.jpg", max_retries=3)
        self.assertEqual(mock_sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
