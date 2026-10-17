"""Backfill bulk selections without replacing curated media or imported themes."""

lazy import json
lazy from collections import Counter
lazy from dataclasses import dataclass, field
lazy from html import escape
lazy from pathlib import Path
lazy from typing import Any
lazy from zipfile import ZipFile

lazy from schema.contract import IDENTITY_FIELDS, validate_entries, validate_entry

lazy from .catalog import EntryIndex, entry_path, merge_ids, new_entry, write_changes

ROOT = Path(__file__).resolve().parents[1]

MAX_ARCHIVE_ENTRIES = 100_000
MAX_SINGLE_ENTRY_BYTES = 1 * 1024 * 1024  # 1 MB
MAX_TOTAL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB
BACKFILL_KINDS = (
    "identifiers",
    "release years",
    "posters",
    "backgrounds",
    "season posters",
    "themes",
)


@dataclass
class ReviewItem:
    title: str
    year: int | None
    media_type: str
    poster_url: str | None = None
    background_url: str | None = None
    youtube_id: str | None = None
    seasons: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])
    added: list[str] = field(default_factory=list[str])


def format_review_markdown(
    review_items: list[ReviewItem], *, max_chars: int = 45_000
) -> str:
    """Render every reviewed change as a collapsible, alphabetical list.

    Raises:
        ValueError: When the list does not fit, since approval applies only
            what the preview shows.
    """
    if not review_items:
        return ""

    sorted_items = sorted(
        review_items,
        key=lambda item: (item.title.lower(), item.year or 0),
    )

    count = len(sorted_items)
    lines = [
        "<details>",
        f"<summary><b>Review Artwork & Theme URLs ({count} items)</b></summary>",
        "<br />",
        "",
    ]
    current_len = sum(len(line) + 1 for line in lines)
    for item in sorted_items:
        item_lines: list[str] = []
        year_str = f" ({item.year})" if item.year else ""
        title = escape(item.title).replace("\n", " ").replace("\r", " ")
        title = title.replace("@", "&#64;").replace("[", "&#91;")
        item_lines.append(f"#### {title}{year_str}")
        if item.added:
            item_lines.append(f"- **Added:** `{', '.join(item.added)}`")
        if item.poster_url:
            item_lines.append(
                f"- **Poster:** [View image](<{escape(item.poster_url)}>)"
            )
        if item.background_url:
            item_lines.append(
                f"- **Background:** [View image](<{escape(item.background_url)}>)"
            )
        if item.youtube_id:
            yt_url = f"https://www.youtube.com/watch?v={item.youtube_id}"
            item_lines.append(
                f"- **YouTube Theme:** [Watch video]({yt_url}) (`{item.youtube_id}`)"
            )
        for s_num, s_url in sorted(item.seasons, key=lambda s: s[0]):
            item_lines.append(
                f"- **Season {s_num} Poster:** [View image](<{escape(s_url)}>)"
            )
        item_lines.append("")

        item_len = sum(len(line) + 1 for line in item_lines)
        if current_len + item_len + 150 > max_chars:
            raise ValueError(
                f"{count:,} changes are too many to review in one comment. "
                "Split the export into smaller archives."
            )
        lines.extend(item_lines)
        current_len += item_len

    lines.append("</details>")
    return "\n".join(lines)


def _merge_seasons(
    existing: dict[str, Any],
    incoming: dict[str, Any],
    changes: list[str],
) -> list[dict[str, Any]] | None:
    """Backfill missing show season posters without changing existing posters."""
    if existing.get("media_type") != "show":
        return None

    exist_seasons: list[dict[str, Any]] = existing.get("seasons") or []
    inc_seasons: list[dict[str, Any]] = incoming.get("seasons") or []

    exist_by_num = {s["season_num"]: dict(s) for s in exist_seasons}
    seasons_changed = False

    for inc_s in inc_seasons:
        s_num = inc_s["season_num"]
        inc_url = inc_s.get("poster_url")
        if not inc_url:
            continue
        if s_num not in exist_by_num:
            exist_by_num[s_num] = {"season_num": s_num, "poster_url": inc_url}
            seasons_changed = True
            changes.append(f"added season {s_num} poster")
        elif not exist_by_num[s_num].get("poster_url"):
            exist_by_num[s_num]["poster_url"] = inc_url
            seasons_changed = True
            changes.append(f"backfilled season {s_num} poster")

    if seasons_changed:
        return [exist_by_num[num] for num in sorted(exist_by_num.keys())]
    return None


def merge_entry(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> tuple[dict[str, Any], bool, list[str]]:
    """Merge incoming entry into existing entry adhering to Rule 1 & Rule 2.

    Returns (updated_dict, changed_bool, list_of_change_descriptions).
    """
    updated = dict(existing)
    # 1. External IDs (enrich missing, verify no conflict)
    changes = merge_ids(updated, incoming)

    # 2. Release Year (enrich missing)
    if updated.get("year") is None and incoming.get("year") is not None:
        updated["year"] = incoming["year"]
        changes.append(f"added year={incoming['year']}")

    # 3. Rule 1: poster_url, background_url, youtube_id_overturedb
    # Never overwrite existing non-empty values. Only backfill when empty or null.
    for art_field in ("poster_url", "background_url", "youtube_id_overturedb"):
        exist_val = existing.get(art_field)
        inc_val = incoming.get(art_field)
        if not exist_val and inc_val:
            # Conflict resolution: OvertureDB adapts when there is a conflict.
            if art_field == "youtube_id_overturedb" and inc_val == existing.get(
                "youtube_id_themerrdb"
            ):
                continue
            updated[art_field] = inc_val
            changes.append(f"backfilled {art_field}")

    # 4. Shows: Season Posters
    new_seasons = _merge_seasons(existing, incoming, changes)
    if new_seasons is not None:
        updated["seasons"] = new_seasons

    # Rule 2: youtube_id_themerrdb is preserved untouched from existing

    return updated, bool(changes), changes


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
            field: incoming.get(field)
            for field in (
                "year",
                *IDENTITY_FIELDS,
                "poster_url",
                "background_url",
                "youtube_id_overturedb",
            )
        },
        # Rule 2: Secondary theme is never populated by bulk import
        youtube_id_themerrdb=None,
    )
    if media_type == "show":
        entry["seasons"] = incoming.get("seasons", [])
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
            entries.extend((info.filename, archive.read(info)) for info in json_infos)
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


def _collect_backfilled_review(
    existing: dict[str, Any], updated: dict[str, Any]
) -> ReviewItem:
    backfilled_poster = (
        updated.get("poster_url")
        if not existing.get("poster_url") and updated.get("poster_url")
        else None
    )
    backfilled_bg = (
        updated.get("background_url")
        if not existing.get("background_url") and updated.get("background_url")
        else None
    )
    backfilled_yt = (
        updated.get("youtube_id_overturedb")
        if not existing.get("youtube_id_overturedb")
        and updated.get("youtube_id_overturedb")
        else None
    )

    exist_seasons_map = {
        s["season_num"]: s.get("poster_url") for s in existing.get("seasons", [])
    }
    backfilled_seasons: list[tuple[int, str]] = []
    for s in updated.get("seasons", []):
        s_num = s["season_num"]
        s_url = s.get("poster_url")
        if s_url and not exist_seasons_map.get(s_num):
            backfilled_seasons.append((s_num, s_url))

    return ReviewItem(
        title=updated["title"],
        year=updated.get("year"),
        media_type=updated["media_type"],
        poster_url=backfilled_poster,
        background_url=backfilled_bg,
        youtube_id=backfilled_yt,
        seasons=backfilled_seasons,
        added=[
            f"{name}={updated[name]}"
            for name in (*IDENTITY_FIELDS, "year")
            if existing.get(name) is None and updated.get(name) is not None
        ],
    )


def _collect_new_review(entry: dict[str, Any]) -> ReviewItem | None:
    seasons = [
        (s["season_num"], s["poster_url"])
        for s in entry.get("seasons", [])
        if s.get("poster_url")
    ]
    if (
        entry.get("poster_url")
        or entry.get("background_url")
        or entry.get("youtube_id_overturedb")
        or seasons
    ):
        return ReviewItem(
            title=entry["title"],
            year=entry.get("year"),
            media_type=entry["media_type"],
            poster_url=entry.get("poster_url"),
            background_url=entry.get("background_url"),
            youtube_id=entry.get("youtube_id_overturedb"),
            seasons=seasons,
            added=[
                f"{name}={entry[name]}"
                for name in IDENTITY_FIELDS
                if entry.get(name) is not None
            ],
        )
    return None


def _backfilled_kinds(item: ReviewItem) -> list[str]:
    added = {change.split("=", 1)[0] for change in item.added}
    present = (
        bool(added - {"year"}),
        "year" in added,
        bool(item.poster_url),
        bool(item.background_url),
        bool(item.seasons),
        bool(item.youtube_id),
    )
    return [kind for kind, has in zip(BACKFILL_KINDS, present, strict=True) if has]


def _process_existing_item(
    existing_path: Path,
    entry: dict[str, Any],
    index: EntryIndex,
) -> tuple[bool, str, ReviewItem | None]:
    """Plan a backfill without writing files."""
    existing = index.entries[existing_path]
    updated, changed, changes = merge_entry(existing, entry)
    if not changed:
        return False, "", None

    validate_entry(updated)
    index.update(existing_path, updated)
    review_item = _collect_backfilled_review(existing, updated)
    return True, f"BACKFILLED {existing_path.name}: {', '.join(changes)}", review_item


def _process_new_item(
    entry: dict[str, Any],
    data_dir: Path,
    index: EntryIndex,
) -> tuple[str, ReviewItem | None]:
    """Plan a new entry file and index it."""
    target_path, created = create_new_entry(entry, data_dir)

    if target_path in index.entries:
        raise ValueError(f"Target path already indexed - {target_path.name}")

    validate_entry(created)
    review_item = _collect_new_review(created)
    if review_item is None:
        raise ValueError("New bulk entries must include artwork or an OvertureDB theme")

    index.put(target_path, created)
    return f"CREATED {target_path.name}: {created['title']}", review_item


def import_bulk_export(
    *,
    overture_dir: Path,
    archive_path: Path | None = None,
    input_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Merge bulk export items into OvertureDB dataset enforcing Rules 1 & 2."""
    data_dir = overture_dir / "data"
    index = EntryIndex.load(overture_dir)
    original_entries = dict(index.entries)

    incoming_entries = load_incoming_entries(
        archive_path=archive_path, input_dir=input_dir
    )

    created_count = 0
    backfilled_count = 0
    backfilled_kinds: Counter[str] = Counter()
    unchanged_count = 0
    skipped_count = 0
    errors: list[str] = []
    details: list[str] = []
    review_items: list[ReviewItem] = []

    for name, raw_entry in incoming_entries:
        try:
            entry = validate_entry(json.loads(raw_entry))
            existing_path = index.find(entry)

            if existing_path is not None:
                changed, detail, review = _process_existing_item(
                    existing_path, entry, index
                )
                if changed:
                    backfilled_count += 1
                    details.append(detail)
                    if review:
                        review_items.append(review)
                        backfilled_kinds.update(_backfilled_kinds(review))
                else:
                    unchanged_count += 1
            else:
                detail, review = _process_new_item(entry, data_dir, index)
                created_count += 1
                details.append(detail)
                if review:
                    review_items.append(review)
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            skipped_count += 1

    # Validate the full catalog consistency for all loaded entries
    validate_entries(list(index.entries.values()))
    if not dry_run and (created_count > 0 or backfilled_count > 0):
        write_changes(original_entries, index.entries, overture_dir)

    return {
        "original_entries": list(original_entries.values()),
        "planned_entries": list(index.entries.values()),
        "total_incoming": len(incoming_entries),
        "created": created_count,
        "backfilled": backfilled_count,
        "backfilled_kinds": {
            kind: backfilled_kinds[kind]
            for kind in BACKFILL_KINDS
            if backfilled_kinds[kind]
        },
        "unchanged": unchanged_count,
        "skipped": skipped_count,
        "errors": errors,
        "details": details,
        "review_markdown": format_review_markdown(review_items),
        "dry_run": dry_run,
    }
