"""Import theme metadata from LizardByte/ThemerrDB into OvertureDB.

Ingests movies and tv shows from ThemerrDB's database branch, updating
existing entries' `youtube_id_themerrdb` or creating new entries when items
do not yet exist in OvertureDB.
"""

lazy import argparse
lazy import json
lazy import re
lazy import sys
lazy from pathlib import Path
lazy from typing import Any, cast
lazy from urllib.parse import parse_qs, urlparse

lazy from schema.contract import (
    IMDB_ID_PATTERN,
    MAX_EXTERNAL_ID,
    TITLE_MAX_LENGTH,
    YEAR_RANGE,
    YOUTUBE_ID_PATTERN,
    validate_entry,
)

lazy from .catalog import EntryIndex, entry_path, new_entry, write_changes

ROOT = Path(__file__).resolve().parents[1]


def extract_youtube_id(value: object) -> str | None:
    """Extract an 11-character YouTube video ID from a URL or raw ID string."""
    if not value or not isinstance(value, str):
        return None

    cleaned = value.strip()
    if YOUTUBE_ID_PATTERN.fullmatch(cleaned):
        return cleaned

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None

    host = parsed.hostname or ""
    path = parsed.path
    if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password:
        return None

    if host in {"www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com"}:
        if path == "/watch":
            params = parse_qs(parsed.query)
            video_ids = params.get("v")
            if video_ids and YOUTUBE_ID_PATTERN.fullmatch(video_ids[0]):
                return video_ids[0]
        elif path.startswith(("/embed/", "/v/", "/shorts/")):
            parts = path.split("/")
            if len(parts) > 2 and YOUTUBE_ID_PATTERN.fullmatch(parts[2]):
                return parts[2]
    elif host in {"youtu.be", "www.youtu.be"}:
        candidate = path.strip("/")
        if YOUTUBE_ID_PATTERN.fullmatch(candidate):
            return candidate

    return None


def parse_year(date_str: object) -> int | None:
    """Extract a 4-digit integer year from an ISO-8601 date string."""
    if not date_str or not isinstance(date_str, str):
        return None
    match = re.prefixmatch(r"(\d{4})", date_str.strip())
    if match:
        year = int(match.group(1))
        first, last = YEAR_RANGE
        if first <= year <= last:
            return year
    return None


def _update_existing(existing_path: Path, index: EntryIndex, youtube_id: str) -> str:
    """Update the imported theme, preserving curated fields."""
    existing = index.entries[existing_path]
    updated = {**existing, "youtube_id_themerrdb": youtube_id}
    if updated["youtube_id_overturedb"] == youtube_id:
        updated["youtube_id_overturedb"] = None
    if updated == existing:
        return "skipped_unchanged"
    validate_entry(updated)

    index.update(existing_path, updated)
    return "updated"


def _create_new_entry(
    item_data: dict[str, Any],
    media_type: str,
    tmdb_id: int,
    youtube_id: str,
    index: EntryIndex,
    data_dir: Path,
) -> str:
    """Plan a new entry with only the imported theme populated."""
    if media_type == "movie":
        raw_title = item_data.get("title") or item_data.get("original_title") or ""
        year = parse_year(item_data.get("release_date"))
    else:
        raw_title = item_data.get("name") or item_data.get("original_name") or ""
        year = parse_year(item_data.get("first_air_date"))

    if not isinstance(raw_title, str):
        return "skipped_invalid"
    title = raw_title.strip()
    if not title:
        return "skipped_invalid"
    if len(title) > TITLE_MAX_LENGTH:
        title = title[:TITLE_MAX_LENGTH].strip()

    entry = new_entry(
        media_type, title, year=year, tmdb_id=tmdb_id, youtube_id_themerrdb=youtube_id
    )
    validate_entry(entry)

    target_path = entry_path(entry, data_dir)
    if target_path.exists():
        raise ValueError(f"Refusing to overwrite unmatched entry: {target_path}")

    index.put(target_path, entry)

    return "added"


def process_themerr_item(
    item_data: dict[str, Any],
    media_type: str,
    index: EntryIndex,
    data_dir: Path,
) -> str:
    """Process a single ThemerrDB JSON record."""
    raw_theme_url = item_data.get("youtube_theme_url")
    youtube_id = extract_youtube_id(raw_theme_url)
    if not youtube_id:
        return "skipped_no_theme"

    tmdb_id = item_data.get("id")
    if type(tmdb_id) is not int or not 0 < tmdb_id <= MAX_EXTERNAL_ID:
        return "skipped_invalid"

    imdb_id = item_data.get("imdb_id")
    clean_imdb_id = (
        imdb_id
        if isinstance(imdb_id, str) and IMDB_ID_PATTERN.fullmatch(imdb_id)
        else None
    )

    existing_path = index.find(
        {"media_type": media_type, "tmdb_id": tmdb_id, "imdb_id": clean_imdb_id}
    )
    if existing_path:
        existing = index.entries[existing_path]
        if existing["tmdb_id"] not in (None, tmdb_id) or (
            clean_imdb_id and existing["imdb_id"] not in (None, clean_imdb_id)
        ):
            raise ValueError(f"Conflicting identifiers for {existing_path}")
        return _update_existing(existing_path, index, youtube_id)

    return _create_new_entry(
        item_data, media_type, tmdb_id, youtube_id, index, data_dir
    )


def import_themerrdb(
    themerr_dir: Path,
    overture_dir: Path,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, int], list[str]]:
    """Apply ThemerrDB to the dataset; return the counts and the titles that lost
    their OvertureDB theme because ThemerrDB now uses the same video."""
    if limit is not None and limit <= 0:
        raise ValueError("Limit must be a positive integer")
    targets = [
        ("movie", themerr_dir / "movies" / "themoviedb"),
        ("show", themerr_dir / "tv_shows" / "themoviedb"),
    ]
    for _, folder in targets:
        if not folder.is_dir():
            raise ValueError(f"ThemerrDB directory does not exist: {folder}")
    data_dir = overture_dir / "data"
    index = EntryIndex.load(overture_dir)
    original_entries = dict(index.entries)

    stats: dict[str, int] = {
        "scanned": 0,
        "updated": 0,
        "added": 0,
        "skipped_no_theme": 0,
        "skipped_unchanged": 0,
        "skipped_invalid": 0,
        "skipped_error": 0,
    }

    for media_type, folder in targets:
        for path in sorted(folder.glob("*.json")):
            if limit and stats["scanned"] >= limit:
                break
            stats["scanned"] += 1

            try:
                item_data = json.loads(path.read_text())
                if not isinstance(item_data, dict):
                    raise ValueError("ThemerrDB record must be an object")
                outcome = process_themerr_item(
                    cast("dict[str, Any]", item_data),
                    media_type,
                    index,
                    data_dir,
                )
            except (OSError, ValueError) as exc:
                print(
                    f"Error importing ThemerrDB file {path}: {exc}",
                    file=sys.stderr,
                )
                stats["skipped_error"] += 1
                continue

            stats[outcome] += 1

    if not dry_run and not stats["skipped_error"]:
        write_changes(original_entries, index.entries, overture_dir)
    return stats, sorted(
        entry["title"]
        for path, entry in index.entries.items()
        if path in original_entries
        and original_entries[path]["youtube_id_overturedb"]
        and not entry["youtube_id_overturedb"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--themerr-dir",
        type=Path,
        required=True,
        help="Path to ThemerrDB checkout (containing movies/ and tv_shows/)",
    )
    parser.add_argument(
        "--overture-dir",
        type=Path,
        default=ROOT,
        help="Path to OvertureDB root directory",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of items processed (for debugging)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and count without writing files to disk",
    )
    parser.add_argument("--output", type=Path, help="Write import counts as JSON")
    args = parser.parse_args()

    print(f"Starting ThemerrDB import (dry_run={args.dry_run})...")
    try:
        stats, lost_themes = import_themerrdb(
            themerr_dir=args.themerr_dir.resolve(),
            overture_dir=args.overture_dir.resolve(),
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    if args.output:
        args.output.write_text(json.dumps({**stats, "lost_themes": lost_themes}))

    print("\n--- ThemerrDB Import Summary ---")
    for key, count in stats.items():
        print(f"{key:>20}: {count}")

    if stats["skipped_error"] > 0:
        print(
            f"\nWarning: Encountered {stats['skipped_error']} errors during import.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
