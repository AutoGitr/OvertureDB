"""The shared artwork link contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "schema"))

from contract import (
    ART_HOSTS,
    art_source,
    canonical_art_url,
    catalog_art_url,
    check_catalog_art_url,
    validate_entry,
)

TMDB = "https://image.tmdb.org/t/p/original/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg"
TPDB = "https://theposterdb.com/api/assets/207889"
FANART = "https://assets.fanart.tv/fanart/movies/603/movieposter/matrix-52b3.jpg"
TVDB = "https://artworks.thetvdb.com/banners/v4/movie/6521/posters/63d3eab3.jpg"
PLEX = "https://metadata-static.plex.tv/0/gracenote/0962f1d53ca0.jpg"
AMAZON = "https://m.media-amazon.com/images/M/MV5BNzQzOTk3OTAtNDQ0Zi00@.jpg"


class CanonicalArtUrlTests(unittest.TestCase):
    def test_every_link_form_becomes_the_full_size_image(self) -> None:
        cases = {
            TMDB: (
                TMDB,
                "http://image.tmdb.org/t/p/original/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg",
                "https://image.tmdb.org/t/p/w342/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg",
                "https://image.tmdb.org/t/p/w600_and_h900_bestv2/"
                "zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg?language=en",
                "https://media.themoviedb.org/t/p/w300_and_h450_face/"
                "zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg",
                "https://www.themoviedb.org/t/p/original/"
                "zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg#zoom",
            ),
            TPDB: (
                TPDB,
                "http://theposterdb.com/poster/207889",
                "https://www.theposterdb.com/poster/207889/?section=posters",
                "https://theposterdb.com/api/assets/207889/view/",
                "  https://THEPOSTERDB.com/api/assets/207889  ",
            ),
            FANART: (
                FANART,
                "https://assets.fanart.tv/preview/movies/603/movieposter/"
                "matrix-52b3.jpg",
                "https://fanart.tv/fanart/movies/603/movieposter/matrix-52b3.jpg",
            ),
            "https://assets.fanart.tv/fanart/20000-days-on-earth-53fb21cfa4b4c.jpg": (
                "https://assets.fanart.tv/preview/20000-days-on-earth-53fb21cfa4b4c.jpg",
            ),
            TVDB: (
                TVDB,
                "https://artworks.thetvdb.com/banners/v4/movie/6521/posters/"
                "63d3eab3_t.jpg",
                "https://thetvdb.com/banners/v4/movie/6521/posters/63d3eab3.jpg",
            ),
            "https://artworks.thetvdb.com/banners/posters/81189-1.jpg": (
                "https://artworks.thetvdb.com/banners/_cache/posters/81189-1.jpg",
                "https://www.thetvdb.com/banners/posters/81189-1_t.jpg",
            ),
            PLEX: (PLEX, "http://metadata-static.plex.tv/0/gracenote/0962f1d53ca0.jpg"),
            AMAZON: (
                AMAZON,
                "https://m.media-amazon.com/images/M/MV5BNzQzOTk3OTAtNDQ0Zi00@"
                "._V1_QL75_UX380_CR0,0,380,562_.jpg",
                "https://images-na.ssl-images-amazon.com/images/M/"
                "MV5BNzQzOTk3OTAtNDQ0Zi00@._V1_SX300.jpg",
                "https://ia.media-imdb.com/images/M/MV5BNzQzOTk3OTAtNDQ0Zi00@.jpg",
            ),
        }
        for canonical, links in cases.items():
            for link in links:
                with self.subTest(link=link):
                    self.assertEqual(canonical_art_url(link), canonical)

    def test_known_sources_must_name_an_image(self) -> None:
        for url in (
            "https://image.tmdb.org/t/p/original/logo.svg",
            "https://image.tmdb.org/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg",
            "https://www.themoviedb.org/movie/603-the-matrix/images/posters",
            "https://theposterdb.com/set/12345",
            "https://theposterdb.com/api/assets/abc",
            "https://fanart.tv/movie/603/the-matrix/",
            "https://artworks.thetvdb.com/banners/",
            "https://metadata-static.plex.tv/",
            "https://m.media-amazon.com/images/I/81abc.jpg",
            "https://image.tmdb.org:8443/t/p/original/a.jpg",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonical_art_url(url)

    def test_other_hosts_only_get_the_general_checks(self) -> None:
        url = "http://images.example.com/poster.webp?size=large#top"
        self.assertEqual(canonical_art_url(f" {url} "), url)
        self.assertIsNone(art_source(url))
        for bad in (
            "ftp://example.com/poster.jpg",
            "/relative/poster.jpg",
            "https://user:secret@example.com/poster.jpg",
            "https://example.com/my poster.jpg",
            "https://example.com\\@image.tmdb.org/t/p/original/a.jpg",
            "https://[::1/poster.jpg",
        ):
            with self.subTest(url=bad), self.assertRaises(ValueError):
                canonical_art_url(bad)

    def test_art_source_names_every_host_alias(self) -> None:
        for url, name in (
            ("https://media.themoviedb.org/t/p/w92/a.jpg", "tmdb"),
            ("https://www.theposterdb.com/poster/1", "tpdb"),
            ("https://fanart.tv/fanart/a.jpg", "fanart"),
            ("https://thetvdb.com/banners/a.jpg", "tvdb"),
            (PLEX, "plex"),
            ("https://ia.media-imdb.com/images/M/a.jpg", "amazon"),
        ):
            with self.subTest(url=url):
                self.assertEqual(art_source(url), name)


class CatalogArtUrlTests(unittest.TestCase):
    def test_catalog_accepts_only_canonical_links_of_catalog_sources(self) -> None:
        self.assertEqual(
            {art_source(url) for url in (TMDB, TPDB, FANART, TVDB, PLEX)},
            {"tmdb", "tpdb", "fanart", "tvdb", "plex"},
        )
        for url in (TMDB, TPDB, FANART, TVDB, PLEX):
            with self.subTest(url=url):
                check_catalog_art_url(url)
                self.assertIn(url.split("/")[2], ART_HOSTS)
        self.assertEqual(
            catalog_art_url("https://image.tmdb.org/t/p/w342/a.jpg"),
            "https://image.tmdb.org/t/p/original/a.jpg",
        )
        for url in (
            AMAZON,
            "https://example.com/poster.jpg",
            "https://image.tmdb.org/t/p/w342/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg",
            "https://www.theposterdb.com/api/assets/207889",
            f"{TPDB}/view",
            f"{TMDB}?language=en",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                check_catalog_art_url(url)

    def test_entries_name_the_offending_artwork_field(self) -> None:
        season: dict[str, object] = {"season_num": 1, "poster_url": TPDB}
        entry: dict[str, object] = {
            "media_type": "show",
            "title": "Show",
            "year": 2020,
            "tmdb_id": 1,
            "tvdb_id": None,
            "imdb_id": None,
            "poster_url": TMDB,
            "background_url": None,
            "youtube_id_overturedb": None,
            "youtube_id_themerrdb": None,
            "seasons": [season],
        }
        self.assertEqual(validate_entry(entry), entry)
        season["poster_url"] = f"{TPDB}/view"
        with self.assertRaisesRegex(ValueError, r"seasons\.0\.poster_url"):
            validate_entry(entry)


if __name__ == "__main__":
    unittest.main()
