"""The publication contract and artifact guarantees, without network access."""

lazy import gzip
lazy import hashlib
lazy import io
lazy import json
lazy import shutil
lazy import socket
lazy import struct
lazy from email.message import Message
lazy from http.client import HTTPMessage
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import MagicMock, patch
lazy from urllib.request import Request

lazy import pytest

lazy from schema.contract import (
    SCHEMA_VERSION,
    dump_catalog,
    read_catalog,
    validate_entries,
    validate_entry,
)
lazy from scripts import catalog


def jpeg(width: int, height: int) -> bytes:
    """Return a JPEG header: an APP0 segment followed by a baseline frame."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + b"\x00" * 10
    return b"\xff\xd8" + app0 + sof


def png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)


def movie(**changes: Any) -> dict[str, Any]:
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


def collection(**changes: Any) -> dict[str, Any]:
    return {
        "media_type": "collection",
        "title": "A Collection",
        "tmdb_id": 10,
        "poster_url": None,
        "background_url": None,
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": "4xdyx5NVUhI",
        **changes,
    }


def header(**changes: Any) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_revision": "a" * 40,
        "generated_at": "2026-09-04T12:00:00Z",
        "third_party_notices": "THIRD_PARTY_NOTICES.md",
        **changes,
    }


def lines(head: dict[str, Any], entries: list[dict[str, Any]]) -> list[bytes]:
    return dump_catalog(head, entries).splitlines()


def test_complete_repository_satisfies_contract() -> None:
    assert catalog.dataset()


def test_entries_have_typed_identifiers_and_bounded_metadata(
    subtests: pytest.Subtests,
) -> None:
    invalid: list[dict[str, Any]] = [
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
        {"poster_url": "http://image.tmdb.org/t/p/original/a.jpg"},
        {"poster_url": "https://user:password@image.tmdb.org/t/p/original/a.jpg"},
        {"unrecognised": True},
    ]
    for change in invalid:
        with subtests.test(change=change), pytest.raises(ValueError):
            validate_entry(movie(**change))


def test_valid_themerrdb_youtube_id() -> None:
    entry = movie(youtube_id_themerrdb="3U6PSWyv5sc")
    assert validate_entry(entry) == entry


def test_youtube_ids_must_be_different() -> None:
    entry = movie(
        youtube_id_overturedb="3U6PSWyv5sc",
        youtube_id_themerrdb="3U6PSWyv5sc",
    )
    with pytest.raises(ValueError):
        validate_entry(entry)


def test_seasons_require_unique_nonnegative_numbers_and_posters(
    subtests: pytest.Subtests,
) -> None:
    season = {
        "season_num": 0,
        "poster_url": "https://image.tmdb.org/t/p/original/s.jpg",
    }
    show = movie(media_type="show", seasons=[season])
    assert validate_entry(show) == show
    for seasons in (
        [
            season,
            {
                **season,
                "poster_url": "https://image.tmdb.org/t/p/original/other.jpg",
            },
        ],
        [{**season, "season_num": -1}],
        [{"season_num": 1}],
    ):
        with subtests.test(seasons=seasons), pytest.raises(ValueError):
            validate_entry({**show, "seasons": seasons})
    with pytest.raises(ValueError):
        validate_entry(movie(media_type="show"))


def test_identity_uniqueness_is_scoped_to_media_type(subtests: pytest.Subtests) -> None:
    assert len(validate_entries([movie(), movie(media_type="show", seasons=[])])) == 2
    for field, value in (("tmdb_id", 1), ("tvdb_id", 10), ("imdb_id", "tt1234567")):
        with subtests.test(field=field), pytest.raises(ValueError):
            validate_entries(
                [movie(**{field: value}), movie(tmdb_id=2) | {field: value}]
            )


def test_catalog_header_and_every_entry_line_are_validated(
    subtests: pytest.Subtests,
) -> None:
    assert list(read_catalog(lines(header(), [movie()]))) == [movie()]
    invalid: list[list[bytes]] = [
        [],
        *(
            lines(header(**change), [])
            for change in (
                {"schema_version": 999},
                {"schema_version": True},
                {"generated_at": "2026-02-30T12:00:00Z"},
                {"generated_at": "2026-09-04"},
                {"source_revision": "unknown"},
                {"third_party_notices": "elsewhere"},
                {"entries": [movie()]},
            )
        ),
        *(
            lines(header(), entries)
            for entries in (
                [movie(), movie(tmdb_id=2, year=False)],
                [movie(year=2026.0)],
                [movie(tmdb_id=1.0)],
            )
        ),
        [b'{"schema_version":1,"schema_version":1}'],
        [*lines(header(), []), b'{"title":"A","title":"B"}'],
        [*lines(header(), [movie()]), b""],
    ]
    for catalog_lines in invalid:
        with subtests.test(lines=catalog_lines), pytest.raises(ValueError):
            list(read_catalog(catalog_lines))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A checkout holding the schema, the notices and one movie entry."""
    (tmp_path / "data/movies").mkdir(parents=True)
    (tmp_path / "data/shows").mkdir()
    (tmp_path / "licenses").mkdir()
    (tmp_path / "licenses" / "THIRD_PARTY_NOTICES.md").write_text("Notices\n")
    shutil.copytree(catalog.ROOT / "schema", tmp_path / "schema")
    (tmp_path / "data/movies/tmdb-1.json").write_text(json.dumps(movie()))
    return tmp_path


@pytest.fixture
def entry(root: Path) -> Path:
    return root / "data/movies/tmdb-1.json"


def build(root: Path, name: str) -> None:
    catalog.build(
        root / name,
        root=root,
        revision="a" * 40,
        generated_at="2026-09-04T12:00:00Z",
    )


def test_publication_is_reproducible_and_digests_match(root: Path) -> None:
    build(root, "first")
    build(root, "second")
    first, second = root / "first", root / "second"
    for path in first.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (second / path.relative_to(first)).read_bytes()
    raw = (first / "catalog.jsonl").read_bytes()
    assert gzip.decompress((first / "catalog.jsonl.gz").read_bytes()) == raw
    assert raw == dump_catalog(header(), [movie()])
    assert list(read_catalog(raw.splitlines())) == [movie()]
    stats = json.loads((first / "stats.json").read_text())
    assert stats["source_revision"] == header()["source_revision"]
    assert stats["generated_at"] == header()["generated_at"]
    assert stats["counts"]["movies"]["titles"] == 1
    assert stats["counts"]["total"]["posters"] == 1
    assert stats["counts"]["shows"]["titles"] == 0
    for name in ("stats.json", "stats-light.svg", "stats-dark.svg"):
        assert name in (first / "SHA256SUMS").read_text()
        assert name in (first / "index.html").read_text()
    assert (first / "stats-light.svg").read_bytes() != (
        first / "stats-dark.svg"
    ).read_bytes()
    for line in (first / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((first / name).read_bytes()).hexdigest() == digest


def test_invalid_entry_prevents_any_publication(root: Path) -> None:
    bad = root / "data/movies/tmdb-2.json"
    bad.write_text(json.dumps(movie(tmdb_id=2, title="")))
    with pytest.raises(ValueError):
        build(root, "public")
    assert not (root / "public").exists()


def test_filename_and_directory_follow_entry_identity(
    subtests: pytest.Subtests,
    root: Path,
    entry: Path,
) -> None:
    for destination in ("data/movies/tmdb-2.json", "data/shows/tmdb-1.json"):
        target = root / destination
        entry.rename(target)
        with subtests.test(destination=destination), pytest.raises(ValueError):
            catalog.dataset(root)
        target.rename(entry)


def test_same_numeric_movie_and_show_id_have_separate_files(root: Path) -> None:
    (root / "data/shows/tmdb-1.json").write_text(
        json.dumps(movie(media_type="show", seasons=[]))
    )
    assert len(catalog.dataset(root)) == 2


@patch.object(catalog, "build")
@patch.object(catalog, "git", return_value=" M data/movies/tmdb-1.json")
def test_cli_requires_source_to_match_its_revision(
    git_output: MagicMock, build: MagicMock
) -> None:
    with (
        patch("sys.argv", ["catalog.py", "build"]),
    ):
        assert catalog.main() == 1
    build.assert_not_called()
    git_output.assert_called_once()


@patch.object(catalog, "build")
@patch.object(catalog, "git", side_effect=["", "a" * 40, "0"])
def test_cli_uses_commit_metadata(git_output: MagicMock, build: MagicMock) -> None:
    with patch("sys.argv", ["catalog.py", "build"]):
        assert catalog.main() == 0
    build.assert_called_once_with(
        catalog.ROOT / "public",
        revision="a" * 40,
        generated_at="1970-01-01T00:00:00Z",
    )


@patch.object(catalog, "dataset")
def test_cli_validate_entry_does_not_load_dataset(
    mock_dataset: MagicMock,
    root: Path,
    entry: Path,
) -> None:
    with (
        patch.object(catalog, "ROOT", root),
        patch("sys.argv", ["catalog.py", "validate", "--entry", str(entry)]),
    ):
        assert catalog.main() == 0
    mock_dataset.assert_not_called()


def test_cli_validate_entry_rejects_invalid_path(
    subtests: pytest.Subtests,
    root: Path,
    entry: Path,
) -> None:
    outside = root / "tmdb-1.json"
    outside.write_text(entry.read_text())
    for path in (outside, root / "nonexistent.json", entry.parent):
        with (
            subtests.test(path=path),
            patch.object(catalog, "ROOT", root),
            patch("sys.argv", ["catalog.py", "validate", "--entry", str(path)]),
        ):
            assert catalog.main() == 1


def test_cli_validate_entry_checks_filename_and_directory(
    subtests: pytest.Subtests,
    root: Path,
    entry: Path,
) -> None:
    for destination in ("data/movies/tmdb-2.json", "data/shows/tmdb-1.json"):
        target = root / destination
        entry.rename(target)
        with (
            subtests.test(destination=destination),
            patch.object(catalog, "ROOT", root),
            patch("sys.argv", ["catalog.py", "validate", "--entry", str(target)]),
        ):
            assert catalog.main() == 1
        target.rename(entry)


def test_cli_validate_entry_rejects_invalid_content(root: Path, entry: Path) -> None:
    entry.write_text(json.dumps(movie(title="")))
    with (
        patch.object(catalog, "ROOT", root),
        patch("sys.argv", ["catalog.py", "validate", "--entry", str(entry)]),
    ):
        assert catalog.main() == 1


@patch.object(catalog, "check_art_url")
def test_cli_validates_multiple_entries_and_checks_each_url_once(
    art: MagicMock,
    root: Path,
    entry: Path,
) -> None:
    paths = [entry, root / "data/movies/tmdb-2.json"]
    for identifier, path in enumerate(paths, start=1):
        path.write_text(
            json.dumps(movie(tmdb_id=identifier)),
        )
    with (
        patch.object(catalog, "ROOT", root),
        patch(
            "sys.argv",
            ["catalog.py", "validate", "--check-urls", "--entry", *map(str, paths)],
        ),
    ):
        assert catalog.main() == 0
    art.assert_called_once_with(movie()["poster_url"])


@patch.object(
    socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]
)
def test_destination_and_redirects_require_public_allowlisted_https(
    lookup: MagicMock,
    subtests: pytest.Subtests,
) -> None:
    catalog.check_art_destination("https://image.tmdb.org/t/p/original/a.jpg")
    assert lookup.call_count == 1
    for url in (
        "http://image.tmdb.org/t/p/original/a.jpg",
        "https://attacker.test/a.jpg",
        "https://image.tmdb.org:8443/t/p/original/a.jpg",
        "https://image.tmdb.org/t/p/original/a.svg",
        "https://theposterdb.com/poster/123",
        "https://theposterdb.com/api/assets/123/view",
        "https://theposterdb.com/api/assets/123/view/",
        "https://image.tmdb.org/t/p/original/a.jpg#fragment",
    ):
        with subtests.test(url=url), pytest.raises(ValueError):
            catalog.check_art_destination(url)
    with pytest.raises(ValueError):
        catalog.ArtRedirectHandler().redirect_request(
            Request("https://image.tmdb.org/t/p/original/a.jpg"),
            io.BytesIO(),
            302,
            "Found",
            HTTPMessage(),
            "http://127.0.0.1/private",
        )
    lookup.return_value.append((2, 1, 6, "", ("127.0.0.1", 443)))
    with pytest.raises(ValueError):
        catalog.check_art_destination("https://image.tmdb.org/t/p/original/a.jpg")


@patch.object(catalog, "check_art_destination")
@patch.object(catalog, "build_opener")
def test_image_probe_reads_only_the_header_and_checks_content(
    opener: MagicMock,
    destination: MagicMock,
    subtests: pytest.Subtests,
) -> None:
    response = MagicMock()
    response.headers = Message()
    response.headers["Content-Type"] = "image/jpeg"
    response.read.side_effect = [jpeg(2000, 3000), b"rest of the image"]
    opener.return_value.open.return_value.__enter__.return_value = response
    assert catalog.check_art_url("https://image.tmdb.org/t/p/original/a.jpg") == (
        2000,
        3000,
    )
    response.read.assert_called_once()
    destination.assert_called_once()
    for invalid_body in (b"<html>Error", b"\xff\xd8\xff\xd9"):
        with subtests.test(invalid_body=invalid_body):
            response.read.side_effect = [invalid_body, b""]
            with pytest.raises(ValueError):
                catalog.check_art_url("https://image.tmdb.org/t/p/original/a.jpg")


@patch.object(catalog, "check_art_destination")
@patch.object(catalog, "build_opener")
def test_image_probe_stops_at_the_byte_limit_without_a_size(
    opener: MagicMock, _destination: MagicMock
) -> None:
    response = MagicMock()
    response.headers = Message()
    response.headers["Content-Type"] = "image/jpeg"
    # A huge metadata segment pushes the frame header past the probe limit.
    huge = b"\xff\xd8\xff\xe1\xff\xff" + b"\x00" * 16384
    response.read.side_effect = [huge, *[b"\x00" * 16384] * 20]
    opener.return_value.open.return_value.__enter__.return_value = response
    with patch.object(catalog, "MAX_PROBE_BYTES", 32768):
        assert (
            catalog.check_art_url("https://image.tmdb.org/t/p/original/a.jpg") is None
        )
    assert response.read.call_count == 2


def test_image_size_reads_png_and_jpeg_headers(subtests: pytest.Subtests) -> None:
    assert catalog.image_size(png(1920, 1080)) == (1920, 1080)
    assert catalog.image_size(jpeg(2000, 3000)) == (2000, 3000)
    progressive = jpeg(10, 20).replace(b"\xff\xc0", b"\xff\xc2")
    assert catalog.image_size(progressive) == (10, 20)
    for data in (
        png(1, 1)[:20],
        png(0, 100),
        jpeg(1, 1)[:-12],
        jpeg(0, 100),
        b"\xff\xd8\xff\xda" + b"\x00" * 20,
        b"\xff\xd8\xff\xe0\x00\x01" + b"\x00" * 20,
        b"GIF89a",
        b"",
    ):
        with subtests.test(data=data):
            assert catalog.image_size(data) is None


def test_aspect_ratio_allows_one_percent(subtests: pytest.Subtests) -> None:
    for kind, width, height, valid in (
        ("poster", 2000, 3000, True),
        ("poster", 1000, 1500, True),
        ("poster", 990, 1500, True),
        ("poster", 980, 1500, False),
        ("background", 3840, 2160, True),
        ("background", 1920, 1080, True),
        ("background", 1920, 1200, False),
        ("poster", 1920, 1080, False),
    ):
        with subtests.test(kind=kind, size=(width, height)):
            problem = catalog.aspect_problem(kind, width, height)
            assert (problem is None) == valid, problem


def test_art_urls_are_deduplicated() -> None:
    entries = [movie(), movie(tmdb_id=2)]
    assert catalog.art_urls(entries) == {movie()["poster_url"]}


def test_parse_retry_after() -> None:
    assert catalog.parse_retry_after("10") == 10.0
    assert catalog.parse_retry_after(None, default=3.0) == 3.0
    assert catalog.parse_retry_after("invalid", default=2.5) == 2.5


@patch.object(catalog.time, "sleep")
@patch.object(catalog, "check_art_destination")
@patch.object(catalog, "build_opener")
def test_image_probe_retries_on_http_429(
    opener: MagicMock,
    destination: MagicMock,
    mock_sleep: MagicMock,
    request: pytest.FixtureRequest,
) -> None:
    rate_error = catalog.HTTPError(
        "https://image.tmdb.org/t/p/original/a.jpg",
        429,
        "Too Many Requests",
        Message(),
        io.BytesIO(b""),
    )
    request.addfinalizer(rate_error.close)
    rate_error.headers["Retry-After"] = "5"
    good_response = MagicMock()
    good_response.headers = Message()
    good_response.headers["Content-Type"] = "image/jpeg"
    good_response.read.return_value = jpeg(2000, 3000)

    cm = MagicMock()
    cm.__enter__.return_value = good_response
    opener.return_value.open.side_effect = [rate_error, cm]

    catalog.check_art_url("https://image.tmdb.org/t/p/original/a.jpg")
    mock_sleep.assert_called_once_with(5.0)


@patch.object(catalog.time, "sleep")
@patch.object(catalog, "check_art_destination")
@patch.object(catalog, "build_opener")
def test_image_probe_exhausts_retries_on_http_429(
    opener: MagicMock,
    destination: MagicMock,
    mock_sleep: MagicMock,
    request: pytest.FixtureRequest,
) -> None:
    rate_error = catalog.HTTPError(
        "https://image.tmdb.org/t/p/original/a.jpg",
        429,
        "Too Many Requests",
        Message(),
        io.BytesIO(b""),
    )
    request.addfinalizer(rate_error.close)
    opener.return_value.open.side_effect = rate_error
    with pytest.raises(catalog.HTTPError):
        catalog.check_art_url(
            "https://image.tmdb.org/t/p/original/a.jpg", max_retries=3
        )
    assert mock_sleep.call_count == 2


def test_an_added_tmdb_id_moves_an_entry_to_its_tmdb_file(tmp_path: Path) -> None:
    root = tmp_path
    old = root / "data/shows/tvdb-2.json"
    old.parent.mkdir(parents=True)
    show = catalog.new_entry(
        "show",
        "Show",
        tvdb_id=2,
        poster_url="https://image.tmdb.org/t/p/original/s.jpg",
    )
    catalog.write_entry_json(old, show)
    index = catalog.EntryIndex.load(root)
    original = dict(index.entries)
    moved = index.update(old, {**show, "tmdb_id": 1})
    assert moved == root / "data/shows/tmdb-1.json"
    assert index.find({"media_type": "show", "tvdb_id": 2}) == moved
    catalog.write_changes(original, index.entries, root)
    assert list((root / "data/shows").iterdir()) == [moved]


def test_merge_ids_adds_missing_identifiers_only() -> None:
    entry = catalog.new_entry("movie", "Alien", tmdb_id=348)
    added = catalog.merge_ids(entry, {"tmdb_id": 348, "imdb_id": "tt0078748"})
    assert added == ["added imdb_id=tt0078748"]
    assert entry["imdb_id"] == "tt0078748"


def test_merge_ids_refuses_a_conflicting_identifier() -> None:
    entry = catalog.new_entry("movie", "Alien", tmdb_id=348)
    with pytest.raises(ValueError, match="Conflicting tmdb_id"):
        catalog.merge_ids(entry, {"tmdb_id": 349})


def test_entry_file_names_follow_the_identifier_rules() -> None:
    for path, valid in (
        ("data/movies/tmdb-348.json", True),
        ("data/shows/imdb-tt0078748.json", True),
        ("data/shows/imdb-0078748.json", False),
        ("data/books/tmdb-348.json", False),
    ):
        assert bool(catalog.ENTRY_FILE.fullmatch(path)) == valid, path


def test_missing_dataset_cannot_publish_empty_catalog(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        catalog.dataset(tmp_path)
