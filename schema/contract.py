"""The version 5 catalog contract, shared with Overture by dataset_contract.py."""

from __future__ import annotations

import json
import re
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

ART_HOSTS: frozenset[str] = frozenset(
    {
        "image.tmdb.org",
        "assets.fanart.tv",
        "theposterdb.com",
        "www.theposterdb.com",
        "artworks.thetvdb.com",
        "metadata-static.plex.tv",
    }
)

_TPDB_API_RE = re.compile(r"^/api/assets/[0-9]+$")
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png"})


def is_allowed_art_url(url: str | None) -> bool:
    """Return True if url is a valid direct artwork destination for OvertureDB."""
    if not url:
        return False
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname not in ART_HOSTS
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or any(ord(char) < 33 for char in url)
        or "\\" in url
    ):
        return False
    if parsed.hostname in {"theposterdb.com", "www.theposterdb.com"}:
        return bool(_TPDB_API_RE.fullmatch(parsed.path))
    return Path(parsed.path).suffix.lower() in _IMAGE_EXTENSIONS


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
    return entry


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
