"""Canonical contribution effects and atomic three-way dataset reconciliation."""

lazy import copy
lazy import hashlib
lazy import json
lazy from pathlib import Path
lazy from typing import Any

lazy from schema.contract import IDENTITY_FIELDS, entry_identities, validate_entries

lazy from .catalog import entry_json, entry_path

type Entry = dict[str, Any]
type Change = dict[str, Any]


class ConflictError(ValueError):
    """The reviewed effect no longer applies without another review."""


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def fields(entry: Entry) -> Entry:
    """Season numbers are keys, never offsets in a mutable array."""
    result = {key: value for key, value in entry.items() if key != "seasons"}
    for season in entry.get("seasons", []):
        result[f"seasons/{season['season_num']}"] = season
    return result


def change(before: Entry | None, after: Entry | None) -> Change:
    old, new = fields(before or {}), fields(after or {})
    return {
        "before": before,
        "after": after,
        "identities": [
            list(identity)
            for identity in sorted(entry_identities(before or after or {}))
        ],
        "fields": {
            key: {"before": old.get(key), "after": new.get(key)}
            for key in sorted(old.keys() | new.keys())
            if old.get(key) != new.get(key)
        },
    }


def between(original: list[Entry], planned: list[Entry]) -> list[Change]:
    """Capture bulk backfills (which never replace existing identifiers)."""
    remaining = list(planned)
    result: list[Change] = []
    for before in original:
        matches = [
            e
            for e in remaining
            if set(entry_identities(e)) & set(entry_identities(before))
        ]
        if len(matches) > 1:
            raise ConflictError("Ambiguous bulk identity")
        after = matches[0] if matches else None
        if after is not None:
            remaining.remove(after)
        if before != after:
            result.append(change(before, after))
    result.extend(change(None, after) for after in remaining)
    return result


def update(current: Entry, before: Entry, after: Entry) -> Entry:
    old, new, live = fields(before), fields(after), fields(current)
    for key in ("media_type", *IDENTITY_FIELDS):
        if live.get(key) not in (old.get(key), new.get(key)):
            raise ConflictError(f"Entry identity changed: {key}")
    for key in old.keys() | new.keys():
        if old.get(key) == new.get(key):
            continue
        if live.get(key) not in (old.get(key), new.get(key)):
            raise ConflictError(f"Reviewed field changed: {key}")
        if key in new:
            live[key] = new[key]
        else:
            live.pop(key, None)
    result = {
        key: value for key, value in live.items() if not key.startswith("seasons/")
    }
    if "seasons" in after:
        result["seasons"] = sorted(
            (value for key, value in live.items() if key.startswith("seasons/")),
            key=lambda season: season["season_num"],
        )
    return result


def apply_one(entries: list[Entry], operation: Change) -> None:
    before, after = operation["before"], operation["after"]
    identities = set(entry_identities(before or after))
    if after:
        identities |= set(entry_identities(after))
    matches = [entry for entry in entries if set(entry_identities(entry)) & identities]
    if len(matches) > 1:
        raise ConflictError("Ambiguous entry identities")
    current = matches[0] if matches else None
    if before is None:
        if current is None:
            entries.append(copy.deepcopy(after))
        elif current != after:
            raise ConflictError("ConflictErroring entry creation")
    elif after is None:
        if current is not None and current != before:
            raise ConflictError("Entry changed since its deletion was reviewed")
        if current is not None:
            entries.remove(current)
    elif current is None:
        raise ConflictError("Reviewed entry disappeared or changed identity")
    else:
        entries[entries.index(current)] = update(current, before, after)


def reconcile(entries: list[Entry], operations: list[Change]) -> list[Entry]:
    """Return a validated copy or fail the entire contribution without writes."""
    result = copy.deepcopy(entries)
    for operation in operations:
        if operation != change(operation["before"], operation["after"]):
            raise ConflictError("Invalid canonical change record")
        apply_one(result, operation)
    return validate_entries(list(result))


def file_changes(original: list[Entry], planned: list[Entry]) -> dict[str, str | None]:
    def files(entries: list[Entry]) -> dict[str, str]:
        return {
            entry_path(entry, Path("data")).as_posix(): entry_json(entry)
            for entry in entries
        }

    before, after = files(original), files(planned)
    return {
        path: after.get(path)
        for path in sorted(before.keys() | after.keys())
        if before.get(path) != after.get(path)
    }
