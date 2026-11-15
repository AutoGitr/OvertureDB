"""Import a bulk export: fill what entries lack, or for an admin, replace them.

Every contribution adds new entries and fills empty identifiers, years, art,
season posters and OvertureDB themes. An admin's contribution also replaces
the art, season posters and OvertureDB themes entries hold. Imported ThemerrDB
themes are never set or replaced.
"""

lazy import json
lazy from collections import Counter
lazy from dataclasses import dataclass, field
lazy from html import escape
lazy from pathlib import Path
lazy from typing import Any, Literal, cast
lazy from zipfile import ZipFile

lazy from schema.contract import (
    ART_FIELDS,
    ENTRY_FOLDERS,
    IDENTITY_FIELDS,
    entry_fields,
    validate_entry,
)

lazy from .catalog import (
    ART_LABELS,
    EntryIndex,
    entry_path,
    merge_ids,
    new_entry,
    planned_file_changes,
)

ROOT = Path(__file__).resolve().parents[1]

MAX_ARCHIVE_ENTRIES = 100_000
MAX_SINGLE_ENTRY_BYTES = 1 * 1024 * 1024  # 1 MB
MAX_TOTAL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB

type Outcome = Literal["new", "updated", "overwritten", "unchanged"]
#: What a contribution did to each entry it names, in the order tables list them.
OUTCOMES: tuple[Outcome, ...] = ("new", "updated", "overwritten", "unchanged")
#: The outcomes reviewers check, those replacing approved values first.
REVIEWED: tuple[Outcome, ...] = ("overwritten", "updated", "new")
OUTCOME_LABELS: dict[Outcome, str] = {
    "new": "New entries",
    "updated": "Filled gaps",
    "overwritten": "Overwritten",
    "unchanged": "Unchanged",
}
#: What a change sets, in the order previews list them.
CHANGE_KINDS = (
    "identifiers",
    "release years",
    "posters",
    "backgrounds",
    "season posters",
    "themes",
)
#: Changes reviewers open links for; identifiers and years are listed as text.
MEDIA_KINDS = frozenset({"posters", "backgrounds", "season posters", "themes"})
type Effect = Literal["added", "filled", "replaced"]
#: How a change lands: in a new entry, in an empty field, or over a held value.
EFFECTS: tuple[Effect, ...] = ("added", "filled", "replaced")
#: The theme field contributions set; ``youtube_id_themerrdb`` is the importer's.
THEME_FIELD = "youtube_id_overturedb"


@dataclass(frozen=True, slots=True)
class Change:
    """One value a contribution sets on an entry."""

    kind: str
    label: str
    new: str | int
    #: The value it replaces, ``None`` when the field was empty.
    old: str | int | None = None


def _season_posters(entry: dict[str, Any]) -> dict[int, str | None]:
    """An entry's season posters by season number."""
    seasons: list[dict[str, Any]] = entry.get("seasons") or []
    return {season["season_num"]: season.get("poster_url") for season in seasons}


def entry_changes(
    existing: dict[str, Any] | None, updated: dict[str, Any]
) -> list[Change]:
    """What *updated* sets that *existing* lacks or holds otherwise.

    A new entry's identifiers and year name it, so they are not changes.
    """
    before = existing or {
        name: updated.get(name) for name in (*IDENTITY_FIELDS, "year")
    }
    changes = [
        Change("identifiers", name, updated[name])
        for name in IDENTITY_FIELDS
        if before.get(name) is None and updated.get(name) is not None
    ]
    if before.get("year") is None and updated.get("year") is not None:
        changes.append(Change("release years", "year", updated["year"]))
    for name in ART_FIELDS:
        if (new := updated.get(name)) and new != before.get(name):
            kind = "backgrounds" if name == "background_url" else "posters"
            changes.append(Change(kind, ART_LABELS[name], new, before.get(name)))
    held = _season_posters(before)
    for number, new in _season_posters(updated).items():
        if new and new != held.get(number):
            changes.append(
                Change(
                    "season posters", f"Season {number} poster", new, held.get(number)
                )
            )
    if (new := updated.get(THEME_FIELD)) and new != before.get(THEME_FIELD):
        changes.append(Change("themes", "Theme", new, before.get(THEME_FIELD)))
    return changes


def entry_outcome(existing: dict[str, Any] | None, changes: list[Change]) -> Outcome:
    """What the contribution did to one entry."""
    if existing is None:
        return "new"
    if not changes:
        return "unchanged"
    return "overwritten" if any(c.old is not None for c in changes) else "updated"


def change_effect(outcome: Outcome, change: Change) -> Effect:
    """How one change lands in an entry with *outcome*."""
    if outcome == "new":
        return "added"
    return "filled" if change.old is None else "replaced"


@dataclass
class ReviewItem:
    """One entry's changes, as reviewers check them."""

    title: str
    year: int | None
    media_type: str
    outcome: Outcome
    changes: list[Change] = field(default_factory=list[Change])


def _image(url: object, text: str = "View image") -> str:
    return f"[{text}](<{escape(str(url))}>)"


def _video(youtube_id: object, text: str = "Watch video") -> str:
    return f"[{text}](https://www.youtube.com/watch?v={youtube_id})"


def _change_line(change: Change) -> str:
    link = _video if change.kind == "themes" else _image
    if change.old is None:
        shown = link(change.new)
        if change.kind == "themes":
            shown += f" (`{change.new}`)"
    else:
        shown = f"{link(change.old, 'Current')} → {link(change.new, 'New')}"
    return f"- **{change.label}:** {shown}"


def _item_lines(item: ReviewItem) -> list[str]:
    year = f" ({item.year})" if item.year else ""
    title = escape(item.title).replace("\n", " ").replace("\r", " ")
    title = title.replace("@", "&#64;").replace("[", "&#91;")
    lines = [f"#### {title}{year}"]
    if added := [
        f"{c.label}={c.new}" for c in item.changes if c.kind not in MEDIA_KINDS
    ]:
        lines.append(f"- **Added:** `{', '.join(added)}`")
    lines.extend(_change_line(c) for c in item.changes if c.kind in MEDIA_KINDS)
    lines.append("")
    return lines


def format_review_markdown(
    review_items: list[ReviewItem], *, max_chars: int = 45_000
) -> str:
    """Render every reviewed change, grouped by outcome, then by media type.

    Overwritten entries come first and open, since they replace what
    reviewers approved before. Entries are alphabetical within each group.

    Raises:
        ValueError: When the list does not fit, since approval applies only
            what the preview shows.
    """
    lines: list[str] = []
    for outcome in REVIEWED:
        group = [item for item in review_items if item.outcome == outcome]
        if not group:
            continue
        opened = " open" if outcome == "overwritten" else ""
        lines.extend(
            [
                f"<details{opened}>",
                f"<summary><b>{OUTCOME_LABELS[outcome]} ({len(group)})</b></summary>",
                "<br />",
                "",
            ]
        )
        for media_type, folder in ENTRY_FOLDERS.items():
            typed = sorted(
                (item for item in group if item.media_type == media_type),
                key=lambda item: (item.title.lower(), item.year or 0),
            )
            if typed:
                lines.extend([f"### {folder.capitalize()}", ""])
            for item in typed:
                lines.extend(_item_lines(item))
        lines.extend(["</details>", ""])
    markdown = "\n".join(lines).strip()
    if len(markdown) + 150 > max_chars:
        raise ValueError(
            f"{len(review_items):,} changed entries exceed the GitHub comment limit. "
            "Split the export into smaller archives (e.g. up to 500 items) "
            "so every change can be verified in the preview."
        )
    return markdown


def _merge_seasons(
    existing: dict[str, Any], incoming: dict[str, Any], *, overwrite: bool
) -> list[dict[str, Any]] | None:
    """A show's season posters with the incoming ones it lacks, or replaces."""
    if existing.get("media_type") != "show":
        return None
    posters = _season_posters(existing)
    for number, url in _season_posters(incoming).items():
        if url and (overwrite or not posters.get(number)):
            posters[number] = url
    return [
        {"season_num": number, "poster_url": url}
        for number, url in sorted(posters.items())
    ]


def merge_entry(
    existing: dict[str, Any], incoming: dict[str, Any], *, overwrite: bool = False
) -> dict[str, Any]:
    """Return *existing* with what *incoming* adds, or with *overwrite*, replaces.

    Identifiers and the year are only ever filled. Art and the OvertureDB theme
    are filled, or replaced with *overwrite*. The imported ThemerrDB theme is
    kept, and an OvertureDB theme equal to it is not taken, so every entry
    keeps a second theme to fall back to.

    Raises:
        ValueError: When an identifier conflicts with the entry's.
    """
    updated = dict(existing)
    merge_ids(updated, incoming)
    if updated.get("year") is None and incoming.get("year") is not None:
        updated["year"] = incoming["year"]
    for name in (*ART_FIELDS, THEME_FIELD):
        value = incoming.get(name)
        if not value or (existing.get(name) and not overwrite):
            continue
        if name == THEME_FIELD and value == existing.get("youtube_id_themerrdb"):
            continue
        updated[name] = value
    seasons = _merge_seasons(existing, incoming, overwrite=overwrite)
    if seasons is not None and seasons != existing.get("seasons", []):
        updated["seasons"] = seasons
    return updated


def create_new_entry(
    incoming: dict[str, Any],
    data_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    """Build a new entry following canonical conventions and Rule 2."""
    media_type = incoming["media_type"]
    entry = new_entry(
        media_type,
        incoming["title"],
        **{
            field: incoming[field]
            for field in entry_fields(media_type)
            if field in incoming
            and field not in {"media_type", "title", "youtube_id_themerrdb"}
        },
        # Rule 2: Secondary theme is never populated by bulk import
        youtube_id_themerrdb=None,
    )
    return entry_path(entry, data_dir), entry


def load_incoming_entries(
    *,
    archive_path: Path | None = None,
    input_dir: Path | None = None,
) -> list[tuple[str, bytes]]:
    """Read bounded candidate records; parse each within its validation boundary."""
    entries: list[tuple[str, bytes]] = []
    if (archive_path is None) == (input_dir is None):
        raise ValueError("Provide exactly one archive or input directory")

    if archive_path is not None:
        with ZipFile(archive_path) as archive:
            json_infos = [
                info
                for info in archive.infolist()
                if info.filename.endswith(".json") and not info.is_dir()
            ]
            _check_sizes([(info.filename, info.file_size) for info in json_infos])
            try:
                entries.extend(
                    (info.filename, archive.read(info)) for info in json_infos
                )
            except (RuntimeError, NotImplementedError) as exc:
                raise ValueError(
                    "Use an unencrypted ZIP with supported compression (ZIP_DEFLATED)."
                ) from exc
    elif input_dir is not None:
        if not input_dir.is_dir():
            raise ValueError(f"Input directory does not exist: {input_dir}")
        json_paths = sorted(input_dir.rglob("*.json"))
        _check_sizes([(p.name, p.stat().st_size) for p in json_paths])
        entries.extend(
            (path.relative_to(input_dir).as_posix(), path.read_bytes())
            for path in json_paths
        )
    return entries


def _check_sizes(sizes: list[tuple[str, int]]) -> None:
    if not sizes:
        raise ValueError("No JSON entries found")
    if len(sizes) > MAX_ARCHIVE_ENTRIES:
        raise ValueError(
            f"Input exceeds maximum allowed entries ({MAX_ARCHIVE_ENTRIES})"
        )
    if sum(size for _, size in sizes) > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise ValueError("Input exceeds maximum allowed uncompressed size (50 MB)")
    for name, size in sizes:
        if size > MAX_SINGLE_ENTRY_BYTES:
            raise ValueError(f"{name} exceeds maximum size (1 MB)")


def _plan_existing_item(
    existing_path: Path, entry: dict[str, Any], index: EntryIndex, *, overwrite: bool
) -> bool:
    """Plan an existing entry's merge without writing files; return if it changes."""
    existing = index.entries[existing_path]
    updated = merge_entry(existing, entry, overwrite=overwrite)
    if updated == existing:
        return False
    validate_entry(updated)
    index.update(existing_path, updated)
    return True


def _plan_new_item(entry: dict[str, Any], data_dir: Path, index: EntryIndex) -> None:
    """Plan a new entry file and index it."""
    target_path, created = create_new_entry(entry, data_dir)
    if target_path in index.entries:
        raise ValueError(f"Target path already indexed - {target_path.name}")
    validate_entry(created)
    if not any(c.kind in MEDIA_KINDS for c in entry_changes(None, created)):
        raise ValueError("New bulk entries must include artwork or an OvertureDB theme")
    index.put(target_path, created)


def import_bulk_export(
    *,
    overture_dir: Path,
    archive_path: Path | None = None,
    input_dir: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Plan merging bulk export items into the catalog, writing nothing.

    *overwrite* replaces the values entries hold.

    Returns:
        The planned file changes, every entry's outcome by media type, every
        change by kind and effect, the errors and the review.
    """
    data_dir = overture_dir / "data"
    original = EntryIndex.load(overture_dir)
    index = EntryIndex()
    for path, entry in original.entries.items():
        index.put(path, entry)

    incoming_entries = load_incoming_entries(
        archive_path=archive_path, input_dir=input_dir
    )
    entries: dict[Outcome, Counter[str]] = {outcome: Counter() for outcome in OUTCOMES}
    errors: list[str] = []
    for name, raw_entry in incoming_entries:
        try:
            incoming = json.loads(raw_entry)
            if isinstance(incoming, dict):
                # Only the importer supplies authoritative imported themes.
                incoming["youtube_id_themerrdb"] = None
            entry = validate_entry(cast("object", incoming))
            existing_path = index.find(entry)
            if existing_path is None:
                _plan_new_item(entry, data_dir, index)
            elif not _plan_existing_item(
                existing_path, entry, index, overwrite=overwrite
            ):
                entries["unchanged"][entry["media_type"]] += 1
        except ValueError as exc:
            errors.append(f"{name}: {exc}")

    additions, deletions = planned_file_changes(
        original.entries, index.entries, overture_dir
    )
    # Count and review final changed entries, not intermediate input records.
    changes: dict[str, Counter[Effect]] = {kind: Counter() for kind in CHANGE_KINDS}
    review_items: list[ReviewItem] = []
    for name in additions:
        entry = index.entries[overture_dir / name]
        previous_path = original.find(entry)
        existing = None if previous_path is None else original.entries[previous_path]
        made = entry_changes(existing, entry)
        outcome = entry_outcome(existing, made)
        entries[outcome][entry["media_type"]] += 1
        for change in made:
            changes[change.kind][change_effect(outcome, change)] += 1
        if any(c.kind in MEDIA_KINDS for c in made):
            review_items.append(
                ReviewItem(
                    title=entry["title"],
                    year=entry.get("year"),
                    media_type=entry["media_type"],
                    outcome=outcome,
                    changes=made,
                )
            )
    # Validation errors take priority over review size; an invalid archive cannot
    # be approved, and contributors need the conflicts to repair it first.
    review_markdown = "" if errors else format_review_markdown(review_items)

    return {
        "additions": additions,
        "deletions": deletions,
        "total_incoming": len(incoming_entries),
        "overwrite": overwrite,
        "entries": {
            outcome: {
                media_type: counts[media_type]
                for media_type in ENTRY_FOLDERS
                if counts[media_type]
            }
            for outcome, counts in entries.items()
        },
        "changes": {
            kind: {effect: counts[effect] for effect in EFFECTS if counts[effect]}
            for kind, counts in changes.items()
            if counts
        },
        "errors": errors,
        "review_markdown": review_markdown,
    }
