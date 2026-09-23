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
    format_media_comparison,
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
"""
        parsed = parse_issue_form(body, "[Movie]: Interstellar (2014)", ["movie"])
        self.assertEqual(parsed.media_type, "movie")
        self.assertEqual(parsed.title, "Interstellar")
        self.assertEqual(parsed.year, 2014)
        self.assertEqual(parsed.tmdb_id, 157336)
        self.assertIsNone(parsed.tvdb_id)
        self.assertEqual(parsed.imdb_id, "tt0816692")
        self.assertEqual(parsed.youtube_id, "abc123abc12")
        self.assertEqual(parsed.modification_reason, MODIFICATION_PLACEHOLDER)

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

        # Attempt contribution replacing existing poster with default placeholder
        body = f"""### Title

Existing Movie

### Year

2024

### TMDB ID

88888

### Poster URL

https://image.tmdb.org/new_p.jpg

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}
"""
        parsed = parse_issue_form(body, "[Movie]: Existing Movie (2024)", ["movie"])
        with self.assertRaises(ValueError) as ctx:
            process_contribution(parsed, self.temp_dir, dry_run=False)
        self.assertIn("Existing artwork or theme is being replaced", str(ctx.exception))
        self.assertIn("replace the placeholder", str(ctx.exception))

    def test_backfill_stub_without_modification_reason(self) -> None:
        # Create existing ThemerrDB stub with no art
        existing_file = self.data_dir / "movies" / "tmdb-11104.json"
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

https://image.tmdb.org/poster.jpg

### Background URL

https://image.tmdb.org/bg.jpg

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}
"""
        parsed = parse_issue_form(body, "[Movie]: Chungking Express (1994)", ["movie"])
        res = process_contribution(parsed, self.temp_dir, dry_run=False)

        self.assertEqual(res["status"], "ok")
        self.assertFalse(res["is_modification"])
        self.assertTrue(res["is_addition"])
        self.assertEqual(res["target"], "data/movies/tmdb-11104.json")
        self.assertEqual(res["tvdb_id"], 4982)
        self.assertEqual(res["imdb_id"], "tt0109424")
        self.assertEqual(res["youtube_id"], "xwGZvpRf1GA")

        saved = json.loads(existing_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["poster_url"], "https://image.tmdb.org/poster.jpg")
        self.assertEqual(saved["background_url"], "https://image.tmdb.org/bg.jpg")
        self.assertEqual(saved["youtube_id_themerrdb"], "xwGZvpRf1GA")
        self.assertEqual(saved["tvdb_id"], 4982)
        self.assertEqual(saved["imdb_id"], "tt0109424")

    def test_submitting_matching_themerrdb_theme_does_not_duplicate_or_fail(
        self,
    ) -> None:
        existing_file = self.data_dir / "movies" / "tmdb-11104.json"
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

https://image.tmdb.org/poster.jpg

### YouTube theme video ID

xwGZvpRf1GA

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}
"""
        parsed = parse_issue_form(body, "[Movie]: Chungking Express (1994)", ["movie"])
        res = process_contribution(parsed, self.temp_dir, dry_run=False)

        self.assertEqual(res["status"], "ok")
        self.assertFalse(res["is_modification"])
        self.assertTrue(res["is_addition"])
        self.assertEqual(res["youtube_id"], "xwGZvpRf1GA")

        saved = json.loads(existing_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["poster_url"], "https://image.tmdb.org/poster.jpg")
        self.assertEqual(saved["youtube_id_themerrdb"], "xwGZvpRf1GA")
        self.assertIsNone(saved["youtube_id_overturedb"])

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

        self.assertIn(
            "- **Old Poster:** [View image](https://image.tmdb.org/old_poster.jpg)",
            res["media_comparison"],
        )
        self.assertIn(
            "- **New Poster:** [View image](https://image.tmdb.org/new_higher_res_poster.jpg)",
            res["media_comparison"],
        )
        self.assertNotIn("Background", res["media_comparison"])
        self.assertNotIn("YouTube", res["media_comparison"])

        # Check updated file
        updated_data = json.loads(existing_file.read_text())
        self.assertEqual(
            updated_data["poster_url"],
            "https://image.tmdb.org/new_higher_res_poster.jpg",
        )
        # Verify themerrdb youtube id preserved untouched
        self.assertEqual(updated_data["youtube_id_themerrdb"], "themerr1111")

    def test_format_media_comparison_all_types(self) -> None:
        existing = {
            "poster_url": "https://image.tmdb.org/old_poster.jpg",
            "background_url": "https://image.tmdb.org/old_bg.jpg",
            "youtube_id_themerrdb": None,
            "youtube_id_overturedb": "oldtheme123",
            "seasons": [
                {"season_num": 1, "poster_url": "https://image.tmdb.org/old_s1.jpg"},
            ],
        }
        updated = {
            "poster_url": "https://image.tmdb.org/old_poster.jpg",  # Unchanged
            "background_url": "https://image.tmdb.org/new_bg.jpg",  # Changed
            "youtube_id_themerrdb": "oldtheme123",
            "youtube_id_overturedb": "newtheme456",  # Changed
            "seasons": [
                {
                    "season_num": 1,
                    "poster_url": "https://image.tmdb.org/new_s1.jpg",
                },  # Changed
                {
                    "season_num": 2,
                    "poster_url": "https://image.tmdb.org/new_s2.jpg",
                },  # Added
            ],
        }
        markdown = format_media_comparison(existing, updated)

        self.assertNotIn("Poster", markdown.splitlines()[0])  # Poster didn't change
        self.assertIn(
            "- **Old Background:** [View image](https://image.tmdb.org/old_bg.jpg)",
            markdown,
        )
        self.assertIn(
            "- **New Background:** [View image](https://image.tmdb.org/new_bg.jpg)",
            markdown,
        )
        self.assertIn(
            "- **Old YouTube Theme:** [Watch video]"
            "(https://www.youtube.com/watch?v=oldtheme123) (`oldtheme123`)",
            markdown,
        )
        self.assertIn(
            "- **New YouTube Theme:** [Watch video]"
            "(https://www.youtube.com/watch?v=newtheme456) (`newtheme456`)",
            markdown,
        )
        self.assertIn(
            "- **Old Season 1 Poster:** [View image](https://image.tmdb.org/old_s1.jpg)",
            markdown,
        )
        self.assertIn(
            "- **New Season 1 Poster:** [View image](https://image.tmdb.org/new_s1.jpg)",
            markdown,
        )
        self.assertIn("- **Old Season 2 Poster:** _None_", markdown)
        self.assertIn(
            "- **New Season 2 Poster:** [View image](https://image.tmdb.org/new_s2.jpg)",
            markdown,
        )

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

        self.assertFalse(res["is_modification"])
        self.assertTrue(res["is_addition"])
        self.assertEqual(res["target"], "data/shows/tvdb-500.json")

        # No duplicate tmdb-1234.json created
        self.assertFalse((self.data_dir / "shows" / "tmdb-1234.json").exists())

        updated = json.loads(show_file.read_text())
        self.assertEqual(
            updated["background_url"], "https://image.tmdb.org/new_background.jpg"
        )
        self.assertEqual(updated["tvdb_id"], 500)

    def test_replacing_theme_requires_reason(self) -> None:
        existing_file = self.data_dir / "movies" / "tmdb-999.json"
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

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}
"""
        parsed = parse_issue_form(body, "[Movie]: Theme Movie (2020)", ["movie"])
        with self.assertRaises(ValueError) as ctx:
            process_contribution(parsed, self.temp_dir, dry_run=False)
        self.assertIn("Existing artwork or theme is being replaced", str(ctx.exception))

        # Replacing theme with reason succeeds
        body_with_reason = body.replace(
            MODIFICATION_PLACEHOLDER, "Better audio quality theme."
        )
        parsed_ok = parse_issue_form(
            body_with_reason, "[Movie]: Theme Movie (2020)", ["movie"]
        )
        res = process_contribution(parsed_ok, self.temp_dir, dry_run=False)
        self.assertTrue(res["is_modification"])
        self.assertEqual(res["youtube_id"], "newTheme222")
        self.assertIn(
            "- **Old YouTube Theme:** [Watch video](https://www.youtube.com/watch?v=oldTheme111)",
            res["media_comparison"],
        )
        self.assertIn(
            "- **New YouTube Theme:** [Watch video](https://www.youtube.com/watch?v=newTheme222)",
            res["media_comparison"],
        )

    def test_adding_overturedb_theme_when_themerrdb_exists_is_not_modification(
        self,
    ) -> None:
        existing_file = self.data_dir / "movies" / "tmdb-999.json"
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

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}
"""
        parsed = parse_issue_form(body, "[Movie]: Theme Movie (2020)", ["movie"])
        res = process_contribution(parsed, self.temp_dir, dry_run=False)
        self.assertEqual(res["status"], "ok")
        self.assertFalse(res["is_modification"])
        self.assertTrue(res["is_addition"])
        self.assertEqual(res["media_comparison"], "")
        self.assertEqual(res["youtube_id"], "overture111")

        saved = json.loads(existing_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["youtube_id_overturedb"], "overture111")
        self.assertEqual(saved["youtube_id_themerrdb"], "themerr1111")

    def test_show_season_poster_replacement_vs_addition(self) -> None:
        show_file = self.data_dir / "shows" / "tvdb-600.json"
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
                        {"season_num": 1, "poster_url": "https://image.tmdb.org/s1.jpg"}
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

1=https://image.tmdb.org/s1_new.jpg

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}
"""
        parsed = parse_issue_form(body_replace, "[Show]: Season Show", ["show"])
        with self.assertRaises(ValueError) as ctx:
            process_contribution(parsed, self.temp_dir, dry_run=False)
        self.assertIn("Existing artwork or theme is being replaced", str(ctx.exception))

        # Adding Season 2 poster without reason succeeds
        body_add = f"""### Title

Season Show

### TVDB ID

600

### Season posters

2=https://image.tmdb.org/s2.jpg

### Reason for modification (if replacing existing artwork or theme)

{MODIFICATION_PLACEHOLDER}
"""
        parsed_add = parse_issue_form(body_add, "[Show]: Season Show", ["show"])
        res = process_contribution(parsed_add, self.temp_dir, dry_run=False)
        self.assertFalse(res["is_modification"])
        self.assertTrue(res["is_addition"])

        updated = json.loads(show_file.read_text())
        self.assertEqual(len(updated["seasons"]), 2)
        self.assertEqual(
            updated["seasons"][0]["poster_url"], "https://image.tmdb.org/s1.jpg"
        )
        self.assertEqual(
            updated["seasons"][1]["poster_url"], "https://image.tmdb.org/s2.jpg"
        )

    def test_cli_json_success(self) -> None:
        import subprocess
        import sys

        body_file = self.temp_dir / "body.md"
        body_file.write_text(
            """### Title

Test Movie

### Year

2024

### TMDB ID

99999

### Poster URL

https://image.tmdb.org/poster.jpg
""",
            encoding="utf-8",
        )
        labels_file = self.temp_dir / "labels.txt"
        labels_file.write_text("contribution\nmovie\n", encoding="utf-8")

        script_path = Path(__file__).resolve().parent / "contribution.py"
        res = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(script_path),
                "--issue-body-file",
                str(body_file),
                "--issue-title",
                "[Movie]: Test Movie (2024)",
                "--labels-file",
                str(labels_file),
                "--repo-root",
                str(self.temp_dir),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        parsed = json.loads(res.stdout)
        self.assertEqual(parsed.get("status"), "ok")
        self.assertEqual(parsed.get("target"), "data/movies/tmdb-99999.json")

    def test_cli_json_error(self) -> None:
        import subprocess
        import sys

        body_file = self.temp_dir / "bad_body.md"
        body_file.write_text(
            "### Title\n\nMovie\n\n### TMDB ID\n\nnot-digits\n", encoding="utf-8"
        )
        labels_file = self.temp_dir / "labels.txt"
        labels_file.write_text("contribution\nmovie\n", encoding="utf-8")

        script_path = Path(__file__).resolve().parent / "contribution.py"
        res = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(script_path),
                "--issue-body-file",
                str(body_file),
                "--issue-title",
                "[Movie]: Movie",
                "--labels-file",
                str(labels_file),
                "--repo-root",
                str(self.temp_dir),
                "--dry-run",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 1)
        parsed = json.loads(res.stdout)
        self.assertEqual(parsed.get("status"), "error")
        self.assertIn("digits only", parsed.get("error", ""))


if __name__ == "__main__":
    unittest.main()
