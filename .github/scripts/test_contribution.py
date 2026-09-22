"""Unit tests for contribution parsing, duplicate handling, and modifications."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from contribution import (
    MODIFICATION_PLACEHOLDER,
    clean_art_url,
    determine_canonical_path,
    extract_field,
    parse_issue_form,
    process_contribution,
)


class ContributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.data_dir = self.temp_dir / "data"
        (self.data_dir / "movies").mkdir(parents=True)
        (self.data_dir / "shows").mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_clean_art_url(self) -> None:
        self.assertIsNone(clean_art_url(None))
        self.assertIsNone(clean_art_url(""))
        tpdb = "https://theposterdb.com/api/assets/12345/view"
        self.assertEqual(
            clean_art_url(tpdb), "https://theposterdb.com/api/assets/12345"
        )
        self.assertEqual(
            clean_art_url(f"{tpdb}/"), "https://theposterdb.com/api/assets/12345"
        )
        normal = "https://image.tmdb.org/t/p/original/test.jpg"
        self.assertEqual(clean_art_url(normal), normal)

    def test_extract_field(self) -> None:
        body = """### Title

Inception

### Year

2010

### TVDB ID

_No response_
"""
        self.assertEqual(extract_field(body, "Title"), "Inception")
        self.assertEqual(extract_field(body, "Year"), "2010")
        self.assertIsNone(extract_field(body, "TVDB ID"))
        self.assertIsNone(extract_field(body, "Nonexistent"))

    def test_parse_movie_form(self) -> None:
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

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}

### Contribution Guidelines

- [X] I have read and followed the Contribution Guidelines.
"""
        parsed = parse_issue_form(body, "[Movie]: Interstellar (2014)", ["movie"])
        self.assertEqual(parsed.media_type, "movie")
        self.assertEqual(parsed.title, "Interstellar")
        self.assertEqual(parsed.year, 2014)
        self.assertEqual(parsed.tmdb_id, 157336)
        self.assertIsNone(parsed.tvdb_id)
        self.assertEqual(parsed.imdb_id, "tt0816692")
        self.assertEqual(parsed.youtube_id, "abc123abc12")
        self.assertTrue(parsed.is_certified)
        self.assertEqual(parsed.modification_reason, MODIFICATION_PLACEHOLDER)

    def test_parse_guidelines_checkbox(self) -> None:
        body = (
            "### Title\n\nMovie\n\n### TMDB ID\n\n1\n\n"
            "### Contribution Guidelines\n\n"
            "- [x] I have read and followed the Contribution Guidelines."
        )
        parsed = parse_issue_form(body, "[Movie]: Movie", ["movie"])
        self.assertTrue(parsed.is_certified)

    def test_parse_invalid_fields(self) -> None:
        base_body = "### Title\n\nMovie\n\n### TMDB ID\n\nabc"
        with self.assertRaises(ValueError) as ctx:
            parse_issue_form(base_body, "[Movie]: Movie", ["movie"])
        self.assertIn("TMDB ID must contain digits only", str(ctx.exception))

        body_bad_imdb = "### Title\n\nMovie\n\n### IMDb ID\n\n12345"
        with self.assertRaises(ValueError) as ctx:
            parse_issue_form(body_bad_imdb, "[Movie]: Movie", ["movie"])
        self.assertIn("IMDb ID must use the format tt", str(ctx.exception))

        body_bad_yt = (
            "### Title\n\nMovie\n\n### TMDB ID\n\n1\n\n"
            "### YouTube theme video ID\n\nhttp://yt.com"
        )
        with self.assertRaises(ValueError) as ctx:
            parse_issue_form(body_bad_yt, "[Movie]: Movie", ["movie"])
        self.assertIn("YouTube video ID must be exactly 11", str(ctx.exception))

    def test_determine_canonical_path(self) -> None:
        movie_path = determine_canonical_path("movie", 100, 200, "tt123", self.data_dir)
        self.assertEqual(movie_path.name, "tmdb-100.json")
        self.assertEqual(movie_path.parent.name, "movies")

        show_path = determine_canonical_path("show", 100, 200, "tt123", self.data_dir)
        self.assertEqual(show_path.name, "tvdb-200.json")
        self.assertEqual(show_path.parent.name, "shows")

    def test_new_entry_creation(self) -> None:
        body = """### Title

New Movie

### Year

2024

### TMDB ID

88888

### Reason for modification (if replacing existing artwork or theme)

"If this modifies an existing entry, replace this text with a reason "
"for the change (e.g. higher resolution, textless, dead link, corrected ID)."
"""
        parsed = parse_issue_form(body, "[Movie]: New Movie (2024)", ["movie"])
        res = process_contribution(parsed, self.temp_dir, dry_run=False)

        self.assertEqual(res["status"], "ok")
        self.assertFalse(res["is_modification"])
        self.assertEqual(res["target"], "data/movies/tmdb-88888.json")
        self.assertTrue((self.temp_dir / "data/movies/tmdb-88888.json").is_file())

    def test_existing_entry_blocks_without_modification_reason(self) -> None:
        # Create existing entry
        existing_file = self.data_dir / "movies" / "tmdb-88888.json"
        existing_file.write_text(
            json.dumps(
                {
                    "media_type": "movie",
                    "title": "Existing Movie",
                    "year": 2024,
                    "tmdb_id": 88888,
                    "tvdb_id": None,
                    "imdb_id": None,
                    "poster_url": "https://image.tmdb.org/p.jpg",
                    "background_url": None,
                    "youtube_id_overturedb": None,
                    "youtube_id_themerrdb": None,
                },
                indent=2,
            )
            + "\n"
        )

        # Attempt contribution with default placeholder
        body = f"""### Title

Existing Movie

### Year

2024

### TMDB ID

88888

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}
"""
        parsed = parse_issue_form(body, "[Movie]: Existing Movie (2024)", ["movie"])
        with self.assertRaises(ValueError) as ctx:
            process_contribution(parsed, self.temp_dir, dry_run=False)
        self.assertIn("Dataset file already exists on main", str(ctx.exception))
        self.assertIn("replace the placeholder", str(ctx.exception))

    def test_existing_entry_allows_with_modification_reason(self) -> None:
        existing_file = self.data_dir / "movies" / "tmdb-88888.json"
        existing_file.write_text(
            json.dumps(
                {
                    "media_type": "movie",
                    "title": "Existing Movie",
                    "year": 2024,
                    "tmdb_id": 88888,
                    "tvdb_id": None,
                    "imdb_id": None,
                    "poster_url": "https://image.tmdb.org/old_poster.jpg",
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

https://image.tmdb.org/new_higher_res_poster.jpg

### Reason for modification (if replacing existing artwork or theme)

Upgrading to official 4K poster art.
"""
        parsed = parse_issue_form(body, "[Movie]: Existing Movie (2024)", ["movie"])
        res = process_contribution(parsed, self.temp_dir, dry_run=False)

        self.assertEqual(res["status"], "ok")
        self.assertTrue(res["is_modification"])
        self.assertEqual(
            res["modification_reason"], "Upgrading to official 4K poster art."
        )
        self.assertIn("new_higher_res_poster.jpg", res["diff"])

        # Check updated file
        updated_data = json.loads(existing_file.read_text())
        self.assertEqual(
            updated_data["poster_url"],
            "https://image.tmdb.org/new_higher_res_poster.jpg",
        )
        # Verify themerrdb youtube id preserved untouched
        self.assertEqual(updated_data["youtube_id_themerrdb"], "themerr1111")

    def test_cross_provider_matching_for_shows(self) -> None:
        # Existing show stored as tvdb-500.json with tmdb_id 1234
        show_file = self.data_dir / "shows" / "tvdb-500.json"
        show_file.write_text(
            json.dumps(
                {
                    "media_type": "show",
                    "title": "My Show",
                    "year": 2021,
                    "tmdb_id": 1234,
                    "tvdb_id": 500,
                    "imdb_id": None,
                    "poster_url": "https://image.tmdb.org/show.jpg",
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

https://image.tmdb.org/new_background.jpg

### Reason for modification (if replacing existing artwork or theme)

Adding missing backdrop.
"""
        parsed = parse_issue_form(body, "[Show]: My Show", ["show"])
        res = process_contribution(parsed, self.temp_dir, dry_run=False)

        self.assertTrue(res["is_modification"])
        self.assertEqual(res["target"], "data/shows/tvdb-500.json")

        # No duplicate tmdb-1234.json created
        self.assertFalse((self.data_dir / "shows" / "tmdb-1234.json").exists())

        updated = json.loads(show_file.read_text())
        self.assertEqual(
            updated["background_url"], "https://image.tmdb.org/new_background.jpg"
        )
        self.assertEqual(updated["tvdb_id"], 500)


if __name__ == "__main__":
    unittest.main()
