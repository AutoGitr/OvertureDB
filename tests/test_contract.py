"""The shared artwork link contract."""

lazy import pytest

lazy from schema.contract import (
    ART_HOSTS,
    art_source,
    canonical_art_url,
    catalog_art_url,
    check_catalog_art_url,
    entry_file_stem,
    validate_entry,
)

TMDB = "https://image.tmdb.org/t/p/original/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg"
TPDB = "https://theposterdb.com/api/assets/207889"
FANART = "https://assets.fanart.tv/fanart/movies/603/movieposter/matrix-52b3.jpg"
TVDB = "https://artworks.thetvdb.com/banners/v4/movie/6521/posters/63d3eab3.jpg"
PLEX = "https://metadata-static.plex.tv/0/gracenote/0962f1d53ca0.jpg"
AMAZON = "https://m.media-amazon.com/images/M/MV5BNzQzOTk3OTAtNDQ0Zi00@.jpg"


def test_every_link_form_becomes_the_full_size_image(subtests: pytest.Subtests) -> None:
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
            "https://assets.fanart.tv/preview/movies/603/movieposter/matrix-52b3.jpg",
            "https://fanart.tv/fanart/movies/603/movieposter/matrix-52b3.jpg",
        ),
        "https://assets.fanart.tv/fanart/20000-days-on-earth-53fb21cfa4b4c.jpg": (
            "https://assets.fanart.tv/preview/20000-days-on-earth-53fb21cfa4b4c.jpg",
        ),
        TVDB: (
            TVDB,
            "https://artworks.thetvdb.com/banners/v4/movie/6521/posters/63d3eab3_t.jpg",
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
            with subtests.test(link=link):
                assert canonical_art_url(link) == canonical


def test_known_sources_must_name_an_image(subtests: pytest.Subtests) -> None:
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
        with subtests.test(url=url), pytest.raises(ValueError):
            canonical_art_url(url)


def test_other_hosts_only_get_the_general_checks(subtests: pytest.Subtests) -> None:
    url = "http://images.example.com/poster.webp?size=large#top"
    assert canonical_art_url(f" {url} ") == url
    assert art_source(url) is None
    for bad in (
        "ftp://example.com/poster.jpg",
        "/relative/poster.jpg",
        "https://user:secret@example.com/poster.jpg",
        "https://example.com/my poster.jpg",
        "https://example.com\\@image.tmdb.org/t/p/original/a.jpg",
        "https://[::1/poster.jpg",
    ):
        with subtests.test(url=bad), pytest.raises(ValueError):
            canonical_art_url(bad)


def test_art_source_names_every_host_alias(subtests: pytest.Subtests) -> None:
    for url, name in (
        ("https://media.themoviedb.org/t/p/w92/a.jpg", "tmdb"),
        ("https://www.theposterdb.com/poster/1", "tpdb"),
        ("https://fanart.tv/fanart/a.jpg", "fanart"),
        ("https://thetvdb.com/banners/a.jpg", "tvdb"),
        (PLEX, "plex"),
        ("https://ia.media-imdb.com/images/M/a.jpg", "amazon"),
    ):
        with subtests.test(url=url):
            assert art_source(url) == name


def test_catalog_accepts_only_canonical_links_of_catalog_sources(
    subtests: pytest.Subtests,
) -> None:
    assert {art_source(url) for url in (TMDB, TPDB, FANART, TVDB, PLEX)} == {
        "tmdb",
        "tpdb",
        "fanart",
        "tvdb",
        "plex",
    }
    for url in (TMDB, TPDB, FANART, TVDB, PLEX):
        with subtests.test(url=url):
            check_catalog_art_url(url)
            assert url.split("/")[2] in ART_HOSTS
    assert (
        catalog_art_url("https://image.tmdb.org/t/p/w342/a.jpg")
        == "https://image.tmdb.org/t/p/original/a.jpg"
    )
    for url in (
        AMAZON,
        "https://example.com/poster.jpg",
        "https://image.tmdb.org/t/p/w342/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg",
        "https://www.theposterdb.com/api/assets/207889",
        f"{TPDB}/view",
        f"{TMDB}?language=en",
    ):
        with subtests.test(url=url), pytest.raises(ValueError):
            check_catalog_art_url(url)


def test_entries_name_the_offending_artwork_field() -> None:
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
    assert validate_entry(entry) == entry
    season["poster_url"] = f"{TPDB}/view"
    with pytest.raises(ValueError, match=r"seasons\.0\.poster_url"):
        validate_entry(entry)


def test_entries_are_named_tmdb_first_for_every_media_type(
    subtests: pytest.Subtests,
) -> None:
    for media_type in ("movie", "show"):
        with subtests.test(media_type=media_type):
            entry = {"media_type": media_type, "tvdb_id": 2, "imdb_id": "tt3"}
            assert entry_file_stem({**entry, "tmdb_id": 1}) == "tmdb-1"
            assert entry_file_stem(entry) == "tvdb-2"
            assert entry_file_stem({"imdb_id": "tt3"}) == "imdb-tt3"
    with pytest.raises(ValueError):
        entry_file_stem({"media_type": "movie"})
