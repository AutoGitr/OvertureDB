"""The version 4 catalog contract, shared with Overture by dataset_contract.py."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator, ValidationError, validators

if TYPE_CHECKING:
    from jsonschema import TypeChecker

SCHEMA_VERSION = 4
SCHEMA_DIR = Path(__file__).resolve().parent


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


ENTRY_SCHEMA = _schema("entry.schema.json")
CATALOG_SCHEMA = _schema("catalog.schema.json")
# Keep the strict type checker when descending into the embedded entry schema.
CATALOG_SCHEMA["properties"]["entries"]["items"] = {
    key: value for key, value in ENTRY_SCHEMA.items() if key not in {"$schema", "$id"}
}
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


def validate_catalog(value: object) -> list[dict[str, Any]]:
    # Validate the envelope first so unsupported versions have a clear error.
    if not isinstance(value, dict):
        raise ValueError("Payload is not a OvertureDB catalog")
    payload = cast("dict[str, Any]", value)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported public dataset schema_version")
    _validate(payload, catalog=True)
    datetime.fromisoformat(payload["generated_at"])
    entries: list[dict[str, Any]] = payload["entries"]
    for entry in entries:
        _seasons(entry)
        _youtube_ids(entry)
    _identities(entries)
    return entries
