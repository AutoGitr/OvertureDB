"""The version 5 catalog contract, shared with Overture by dataset_contract.py."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, ValidationError, validators

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from jsonschema import TypeChecker

SCHEMA_VERSION = 5
SCHEMA_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class _ArtSource:
    """One art source and the shape of the links it serves.

    ``path`` matches every link form the source serves for one image (sizes,
    thumbnails, page and viewer links); ``canonical`` rebuilds the full-size
    image path from its named groups.
    """

    name: str
    label: str
    host: str
    aliases: frozenset[str]
    path: re.Pattern[str]
    canonical: str
    example: str
    catalog: bool = True


_IMAGE_FILE = r"[^/]+\.(?:jpe?g|png)"
_ART_SOURCES = (
    _ArtSource(
        name="tmdb",
        label="TMDB",
        host="image.tmdb.org",
        aliases=frozenset(
            {"themoviedb.org", "www.themoviedb.org", "media.themoviedb.org"}
        ),
        # Every size (w342, w600_and_h900_bestv2, ...) is the same file.
        path=re.compile(rf"/t/p/[^/]+/(?P<file>{_IMAGE_FILE})", re.IGNORECASE),
        canonical="/t/p/original/{file}",
        example="https://image.tmdb.org/t/p/original/<file>.jpg",
    ),
    _ArtSource(
        name="tpdb",
        label="ThePosterDB",
        host="theposterdb.com",
        aliases=frozenset({"www.theposterdb.com"}),
        path=re.compile(r"/(?:poster|api/assets)/(?P<id>[0-9]+)(?:/view)?/?"),
        canonical="/api/assets/{id}",
        example="https://theposterdb.com/api/assets/<id>",
    ),
    _ArtSource(
        name="fanart",
        label="fanart.tv",
        host="assets.fanart.tv",
        aliases=frozenset({"fanart.tv", "www.fanart.tv"}),
        # /preview/ serves a thumbnail of the /fanart/ original.
        path=re.compile(
            rf"/(?:fanart|preview)/(?P<file>(?:[^/]+/)*{_IMAGE_FILE})", re.IGNORECASE
        ),
        canonical="/fanart/{file}",
        example="https://assets.fanart.tv/fanart/<file>.jpg",
    ),
    _ArtSource(
        name="tvdb",
        label="TheTVDB",
        host="artworks.thetvdb.com",
        aliases=frozenset({"thetvdb.com", "www.thetvdb.com"}),
        # A _t suffix or the _cache/ folder serves a thumbnail of the original.
        path=re.compile(
            r"/banners/(?:_cache/)?(?P<folder>(?:[^/]+/)*)"
            r"(?P<stem>[^/]+?)(?:_t)?(?P<ext>\.(?:jpe?g|png))",
            re.IGNORECASE,
        ),
        canonical="/banners/{folder}{stem}{ext}",
        example="https://artworks.thetvdb.com/banners/<path>.jpg",
    ),
    _ArtSource(
        name="plex",
        label="Plex",
        host="metadata-static.plex.tv",
        aliases=frozenset(),
        path=re.compile(rf"/(?P<file>(?:[^/]+/)*{_IMAGE_FILE})", re.IGNORECASE),
        canonical="/{file}",
        example="https://metadata-static.plex.tv/<path>.jpg",
    ),
    _ArtSource(
        name="amazon",
        label="Amazon",
        host="m.media-amazon.com",
        aliases=frozenset({"images-na.ssl-images-amazon.com", "ia.media-imdb.com"}),
        # Size and crop modifiers sit between the id and the extension.
        path=re.compile(
            r"/images/M/(?P<id>[^/.]+)(?:\.[^/]*)?(?P<ext>\.(?:jpe?g|png))",
            re.IGNORECASE,
        ),
        canonical="/images/M/{id}{ext}",
        example="https://m.media-amazon.com/images/M/<id>.jpg",
        catalog=False,
    ),
)
_ART_SOURCE_BY_HOST: dict[str, _ArtSource] = {
    host: source for source in _ART_SOURCES for host in (source.host, *source.aliases)
}
#: Hosts of the art sources catalog entries may link to.
ART_HOSTS: frozenset[str] = frozenset(
    source.host for source in _ART_SOURCES if source.catalog
)


def _art_source_of(url: str) -> _ArtSource | None:
    try:
        hostname = urlsplit(url.strip()).hostname
    except ValueError:
        return None
    return _ART_SOURCE_BY_HOST.get((hostname or "").rstrip("."))


def art_source(url: str) -> str | None:
    """Return the name of the known art source a link points at, if any."""
    source = _art_source_of(url)
    return source.name if source else None


def canonical_art_url(url: str) -> str:
    """Return the one canonical form of an artwork link.

    A link to a known art source, in any form it serves an image under
    (resized, thumbnail, alias host, viewer or page link), becomes that
    image's full-size URL on the source's own host over HTTPS. Links to other
    hosts are returned unchanged once they pass the general checks.

    Raises:
        ValueError: When the link is not a usable http(s) URL, or points at
            a known art source without naming one of its images.
    """
    url = url.strip()
    if any(ord(char) < 33 or char == "\\" for char in url):
        raise ValueError("Artwork link must not contain spaces or backslashes")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ValueError("Artwork link is not a valid URL") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Artwork link must be an http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Artwork link must not contain credentials")
    source = _ART_SOURCE_BY_HOST.get(parts.hostname.rstrip("."))
    if source is None:
        return url
    if port not in (None, 80, 443):
        raise ValueError(f"{source.label} artwork links must use the standard port")
    match = source.path.fullmatch(parts.path)
    if match is None:
        raise ValueError(
            f"{source.label} artwork links must point at an image, "
            f"like {source.example}"
        )
    return f"https://{source.host}{source.canonical.format_map(match.groupdict())}"


def catalog_art_url(url: str) -> str:
    """Return the canonical form of an artwork link the catalog accepts.

    Raises:
        ValueError: When the link is unusable or its source is not one the
            catalog links to.
    """
    canonical = canonical_art_url(url)
    source = _art_source_of(canonical)
    if source is None or not source.catalog:
        *others, last = (item.label for item in _ART_SOURCES if item.catalog)
        raise ValueError(f"Artwork must come from {', '.join(others)} or {last}")
    return canonical


def check_catalog_art_url(url: str) -> None:
    """Require *url* to be the canonical link of catalog artwork.

    Raises:
        ValueError: When it is not, naming the canonical form when one exists.
    """
    canonical = catalog_art_url(url)
    if canonical != url:
        raise ValueError(f"Artwork link must use its canonical form {canonical}")


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


ENTRY_SCHEMA = _schema("entry.schema.json")
CATALOG_SCHEMA = _schema("catalog.schema.json")
Draft202012Validator.check_schema(ENTRY_SCHEMA)
Draft202012Validator.check_schema(CATALOG_SCHEMA)


# JSON scalar types are preserved: IDs and years are never coerced from strings,
# floats, or booleans before they become database keys.
def _integer(_checker: TypeChecker, value: object) -> bool:
    return type(value) is int


# jsonschema's factory and generated validate method have incomplete type stubs.
_Validator = validators.create(  # pyright: ignore[reportUnknownMemberType]
    meta_schema=Draft202012Validator.META_SCHEMA,
    validators=Draft202012Validator.VALIDATORS,
    type_checker=cast("TypeChecker", Draft202012Validator.TYPE_CHECKER).redefine(
        "integer", _integer
    ),
)
_ENTRY_VALIDATOR = _Validator(ENTRY_SCHEMA)
_CATALOG_VALIDATOR = _Validator(CATALOG_SCHEMA)


def _validate(value: object, *, catalog: bool) -> None:
    validator = _CATALOG_VALIDATOR if catalog else _ENTRY_VALIDATOR
    try:
        validator.validate(value)  # pyright: ignore[reportUnknownMemberType]
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise ValueError(
            f"Dataset contract violation at {path}: {exc.message}"
        ) from exc


def validate_entry(value: object) -> dict[str, Any]:
    _validate(value, catalog=False)
    entry = cast("dict[str, Any]", value)
    _seasons(entry)
    _youtube_ids(entry)
    _art_urls(entry)
    return entry


def _art_urls(entry: dict[str, Any]) -> None:
    fields = [
        ("poster_url", entry["poster_url"]),
        ("background_url", entry["background_url"]),
        *(
            (f"seasons.{index}.poster_url", season["poster_url"])
            for index, season in enumerate(entry.get("seasons", []))
        ),
    ]
    for path, url in fields:
        if url is None:
            continue
        try:
            check_catalog_art_url(url)
        except ValueError as exc:
            raise ValueError(f"Dataset contract violation at {path}: {exc}") from exc


def _youtube_ids(entry: dict[str, Any]) -> None:
    yt_overturedb = entry.get("youtube_id_overturedb")
    yt_themerrdb = entry.get("youtube_id_themerrdb")
    if (
        yt_overturedb is not None
        and yt_themerrdb is not None
        and yt_overturedb == yt_themerrdb
    ):
        raise ValueError(
            "youtube_id_overturedb and youtube_id_themerrdb must be different"
        )


def _seasons(entry: dict[str, Any]) -> None:
    numbers = [season["season_num"] for season in entry.get("seasons", [])]
    if len(set(numbers)) != len(numbers):
        raise ValueError("Dataset entry contains duplicate season numbers")


def validate_entries(values: list[object]) -> list[dict[str, Any]]:
    entries = [validate_entry(value) for value in values]
    _identities(entries)
    return entries


def _identities(entries: list[dict[str, Any]]) -> None:
    identities: set[tuple[str, str, str | int]] = set()
    for entry in entries:
        for field in ("tmdb_id", "tvdb_id", "imdb_id"):
            value = entry[field]
            if value is None:
                continue
            key = (entry["media_type"], field, value)
            if key in identities:
                raise ValueError(f"Duplicate dataset identity: {key}")
            identities.add(key)


def validate_header(value: object) -> dict[str, Any]:
    # Check the version first so unsupported catalogs have a clear error.
    if not isinstance(value, dict):
        raise ValueError("Payload is not a OvertureDB catalog")
    header = cast("dict[str, Any]", value)
    if header.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported public dataset schema_version")
    _validate(header, catalog=True)
    datetime.fromisoformat(header["generated_at"])
    return header


def dump_catalog(header: dict[str, Any], entries: Iterable[dict[str, Any]]) -> bytes:
    """Serialize JSON Lines: the header record, then one entry per line."""
    return b"".join(
        json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
        for record in (header, *entries)
    )


def read_catalog(lines: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    """Validate the header line, then yield each entry line once it is valid.

    Identity uniqueness spans the whole catalog, so callers enforce it.
    """
    records = iter(lines)
    validate_header(_record(next(records, b"")))
    for line in records:
        yield validate_entry(_record(line))


def _record(line: bytes) -> object:
    return json.loads(line, object_pairs_hook=_unique_keys)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    record = dict(pairs)
    if len(record) != len(pairs):
        raise ValueError("Catalog record repeats a key")
    return record
