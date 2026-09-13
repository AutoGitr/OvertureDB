"""Import theme metadata from LizardByte/ThemerrDB into OvertureDB.

Ingests movies and tv shows from ThemerrDB's database branch, updating
existing entries' `youtube_id_secondary` or creating new entries when items
do not yet exist in OvertureDB.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "schema"))

from contract import validate_entries, validate_entry  # noqa: E402

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
IMDB_ID_RE = re.compile(r"^tt[0-9]+$")

type ExistingIndex = tuple[
    dict[tuple[str, int], Path],
    dict[tuple[str, str], Path],
    dict[Path, dict[str, Any]],
]


def extract_youtube_id(value: str | None) -> str | None:
    """Extract an 11-character YouTube video ID from a URL or raw ID string."""
    if not value or not isinstance(value, str):
        return None

    cleaned = value.strip()
    if YOUTUBE_ID_RE.fullmatch(cleaned):
        return cleaned

    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None

    host = parsed.hostname or ""
    path = parsed.path

    if host in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        if path == "/watch":
            params = parse_qs(parsed.query)
            video_ids = params.get("v")
            if video_ids and YOUTUBE_ID_RE.fullmatch(video_ids[0]):
                return video_ids[0]
        elif path.startswith(("/embed/", "/v/")):
            parts = path.split("/")
            if len(parts) > 2 and YOUTUBE_ID_RE.fullmatch(parts[2]):
                return parts[2]
    elif host in {"youtu.be", "www.youtu.be"}:
        candidate = path.strip("/")
        if YOUTUBE_ID_RE.fullmatch(candidate):
            return candidate

    return None


def parse_year(date_str: str | None) -> int | None:
    """Extract a 4-digit integer year from an ISO-8601 date string."""
    if not date_str or not isinstance(date_str, str):
        return None
    match = re.match(r"^(\d{4})", date_str.strip())
    if match:
        year = int(match.group(1))
        if 1000 <= year <= 9999:
            return year
    return None


def index_existing_entries(data_dir: Path) -> ExistingIndex:
    """Index existing OvertureDB entries by TMDB and IMDb identities."""
    by_tmdb: dict[tuple[str, int], Path] = {}
    by_imdb: dict[tuple[str, str], Path] = {}
    loaded: dict[Path, dict[str, Any]] = {}

    if not data_dir.is_dir():
        raise ValueError(f"Dataset directory does not exist: {data_dir}")
    paths = sorted(data_dir.rglob("*.json"))
    entries = validate_entries(
        [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    )
    for path, entry in zip(paths, entries, strict=True):
        media_type = entry["media_type"]
        tmdb_id = entry["tmdb_id"]
        imdb_id = entry["imdb_id"]
        if tmdb_id is not None:
            by_tmdb[(media_type, tmdb_id)] = path
        if imdb_id is not None:
            by_imdb[(media_type, imdb_id)] = path
        loaded[path] = entry

    return by_tmdb, by_imdb, loaded


def _update_existing(
    existing_path: Path,
    loaded_entries: dict[Path, dict[str, Any]],
    youtube_id: str,
    source: dict[str, str],
    *,
    dry_run: bool,
) -> str:
    """Update the imported theme and its attribution, preserving curated fields."""
    existing = loaded_entries[existing_path]
    updated = {**existing, "youtube_id_secondary": youtube_id}
    sources = list(existing.get("sources", []))
    if source not in sources:
        sources.append(source)
    updated["sources"] = sources
    if updated == existing:
        return "skipped_unchanged"
    validate_entry(updated)

    if not dry_run:
        existing_path.write_text(
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    loaded_entries[existing_path] = updated
    return "updated"


def _create_new_entry(
    item_data: dict[str, Any],
    media_type: str,
    tmdb_id: int,
    youtube_id: str,
    source: dict[str, str],
    by_tmdb: dict[tuple[str, int], Path],
    loaded_entries: dict[Path, dict[str, Any]],
    data_dir: Path,
    *,
    dry_run: bool,
) -> str:
    """Build and write a new entry with only secondary theme populated."""
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
    if len(title) > 200:
        title = title[:200].strip()

    new_entry: dict[str, Any] = {
        "media_type": media_type,
        "title": title,
        "year": year,
        "tmdb_id": tmdb_id,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": None,
        "background_url": None,
        "youtube_id": None,
        "youtube_id_secondary": youtube_id,
    }

    if media_type == "show":
        new_entry["seasons"] = []
    new_entry["sources"] = [source]

    validate_entry(new_entry)

    target_dir = data_dir / ("movies" if media_type == "movie" else "shows")
    target_path = target_dir / f"tmdb-{tmdb_id}.json"
    if target_path.exists():
        raise ValueError(f"Refusing to overwrite unmatched entry: {target_path}")

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(new_entry, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    loaded_entries[target_path] = new_entry
    by_tmdb[(media_type, tmdb_id)] = target_path

    return "added"


def process_themerr_item(
    item_data: dict[str, Any],
    media_type: str,
    by_tmdb: dict[tuple[str, int], Path],
    by_imdb: dict[tuple[str, str], Path],
    loaded_entries: dict[Path, dict[str, Any]],
    data_dir: Path,
    *,
    dry_run: bool = False,
) -> str:
    """Process a single ThemerrDB JSON record."""
    raw_theme_url = item_data.get("youtube_theme_url")
    youtube_id = extract_youtube_id(raw_theme_url)
    if not youtube_id:
        return "skipped_no_theme"

    tmdb_id = item_data.get("id")
    if type(tmdb_id) is not int or not 0 < tmdb_id <= 9223372036854775807:
        return "skipped_invalid"

    imdb_id = item_data.get("imdb_id")
    clean_imdb_id = (
        imdb_id if isinstance(imdb_id, str) and IMDB_ID_RE.fullmatch(imdb_id) else None
    )
    folder = "movies" if media_type == "movie" else "tv_shows"
    source = {
        "name": "ThemerrDB",
        "url": (
            "https://github.com/LizardByte/ThemerrDB/blob/database/"
            f"{folder}/themoviedb/{tmdb_id}.json"
        ),
        "license": "BSD-3-Clause",
    }

    existing_path = by_tmdb.get((media_type, tmdb_id))
    imdb_path = by_imdb.get((media_type, clean_imdb_id)) if clean_imdb_id else None
    if existing_path and imdb_path and existing_path != imdb_path:
        raise ValueError(
            f"Conflicting TMDB and IMDb matches for {media_type} {tmdb_id}"
        )
    existing_path = existing_path or imdb_path

    if existing_path:
        existing = loaded_entries[existing_path]
        if existing["tmdb_id"] not in (None, tmdb_id) or (
            clean_imdb_id and existing["imdb_id"] not in (None, clean_imdb_id)
        ):
            raise ValueError(f"Conflicting identifiers for {existing_path}")
        return _update_existing(
            existing_path,
            loaded_entries,
            youtube_id,
            source,
            dry_run=dry_run,
        )

    return _create_new_entry(
        item_data,
        media_type,
        tmdb_id,
        youtube_id,
        source,
        by_tmdb,
        loaded_entries,
        data_dir,
        dry_run=dry_run,
    )


def import_themerrdb(
    themerr_dir: Path,
    overture_dir: Path,
    *,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Scan ThemerrDB directories and apply updates to OvertureDB entries."""
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
    by_tmdb, by_imdb, loaded_entries = index_existing_entries(data_dir)

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
                item_data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(item_data, dict):
                    raise ValueError("ThemerrDB record must be an object")
                outcome = process_themerr_item(
                    item_data,
                    media_type,
                    by_tmdb,
                    by_imdb,
                    loaded_entries,
                    data_dir,
                    dry_run=dry_run,
                )
            except (OSError, ValueError) as exc:
                print(  # noqa: T201
                    f"Error importing ThemerrDB file {path}: {exc}",
                    file=sys.stderr,
                )
                stats["skipped_error"] += 1
                continue

            stats[outcome] += 1

    return stats


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
    args = parser.parse_args()

    print(f"Starting ThemerrDB import (dry_run={args.dry_run})...")  # noqa: T201
    try:
        stats = import_themerrdb(
            themerr_dir=args.themerr_dir.resolve(),
            overture_dir=args.overture_dir.resolve(),
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    print("\n--- ThemerrDB Import Summary ---")  # noqa: T201
    for key, count in stats.items():
        print(f"{key:>20}: {count}")  # noqa: T201

    if stats["skipped_error"] > 0:
        print(  # noqa: T201
            f"\nWarning: Encountered {stats['skipped_error']} errors during import.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
