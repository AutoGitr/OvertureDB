"""Import bulk exported selections into OvertureDB.

Enforces:
1. Rule 1: Existing poster_url, background_url, and youtube_id_overturedb are
   never overwritten. Only missing/null fields are backfilled.
2. Rule 2: youtube_id_themerrdb is managed exclusively by themerrdb and is never
   altered or populated by bulk imports.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "schema"))

from contract import validate_entries, validate_entry  # noqa: E402

MAX_ARCHIVE_ENTRIES = 1000
MAX_SINGLE_ENTRY_BYTES = 1 * 1024 * 1024  # 1 MB
MAX_TOTAL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB

type ExistingIndex = tuple[
    dict[tuple[str, int], Path],
    dict[tuple[str, int], Path],
    dict[tuple[str, str], Path],
    dict[Path, dict[str, Any]],
]


def index_existing_entries(data_dir: Path) -> ExistingIndex:
    """Index existing OvertureDB entries by TMDB, TVDB, and IMDb identities."""
    by_tmdb: dict[tuple[str, int], Path] = {}
    by_tvdb: dict[tuple[str, int], Path] = {}
    by_imdb: dict[tuple[str, str], Path] = {}
    loaded: dict[Path, dict[str, Any]] = {}

    if not data_dir.is_dir():
        raise ValueError(f"Dataset directory does not exist: {data_dir}")

    paths = sorted(data_dir.rglob("*.json"))
    for path in paths:
        entry = json.loads(path.read_text(encoding="utf-8"))
        media_type = entry["media_type"]
        tmdb_id = entry.get("tmdb_id")
        tvdb_id = entry.get("tvdb_id")
        imdb_id = entry.get("imdb_id")

        if tmdb_id is not None:
            by_tmdb[(media_type, tmdb_id)] = path
        if tvdb_id is not None:
            by_tvdb[(media_type, tvdb_id)] = path
        if imdb_id is not None:
            by_imdb[(media_type, imdb_id)] = path
        loaded[path] = entry

    return by_tmdb, by_tvdb, by_imdb, loaded


def find_existing_entry(
    entry: dict[str, Any],
    by_tmdb: dict[tuple[str, int], Path],
    by_tvdb: dict[tuple[str, int], Path],
    by_imdb: dict[tuple[str, str], Path],
) -> Path | None:
    """Locate an existing entry file across TMDB, TVDB, or IMDb identifiers."""
    media_type = entry["media_type"]
    tmdb_id = entry.get("tmdb_id")
    tvdb_id = entry.get("tvdb_id")
    imdb_id = entry.get("imdb_id")

    matches: set[Path] = set()
    if tmdb_id is not None and (media_type, tmdb_id) in by_tmdb:
        matches.add(by_tmdb[(media_type, tmdb_id)])
    if tvdb_id is not None and (media_type, tvdb_id) in by_tvdb:
        matches.add(by_tvdb[(media_type, tvdb_id)])
    if imdb_id is not None and (media_type, imdb_id) in by_imdb:
        matches.add(by_imdb[(media_type, imdb_id)])

    if len(matches) > 1:
        raise ValueError(
            f"Conflicting existing files matched for entry: {[p.name for p in matches]}"
        )
    return next(iter(matches), None)


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
    changes: list[str] = []

    # 1. External IDs (enrich missing, verify no conflict)
    for id_field in ("tmdb_id", "tvdb_id", "imdb_id"):
        inc_val = incoming.get(id_field)
        exist_val = existing.get(id_field)
        if inc_val is not None:
            if exist_val is None:
                updated[id_field] = inc_val
                changes.append(f"added {id_field}={inc_val}")
            elif exist_val != inc_val:
                raise ValueError(
                    f"Conflicting {id_field}: existing={exist_val}, incoming={inc_val}"
                )

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
    folder = "movies" if media_type == "movie" else "shows"

    # Canonical prefixes: tvdb preferred for shows; tmdb preferred for movies
    providers = (
        ("tvdb", "tmdb", "imdb") if media_type == "show" else ("tmdb", "tvdb", "imdb")
    )
    identity = next(
        f"{p}-{incoming[f'{p}_id']}"
        for p in providers
        if incoming.get(f"{p}_id") is not None
    )
    target_path = data_dir / folder / f"{identity}.json"

    entry: dict[str, Any] = {
        "media_type": media_type,
        "title": incoming["title"],
        "year": incoming.get("year"),
        "tmdb_id": incoming.get("tmdb_id"),
        "tvdb_id": incoming.get("tvdb_id"),
        "imdb_id": incoming.get("imdb_id"),
        "poster_url": incoming.get("poster_url"),
        "background_url": incoming.get("background_url"),
        "youtube_id_overturedb": incoming.get("youtube_id_overturedb"),
        # Rule 2: Secondary theme is never populated by bulk import
        "youtube_id_themerrdb": None,
    }
    if media_type == "show":
        entry["seasons"] = incoming.get("seasons", [])

    return target_path, entry


def load_incoming_entries(
    *,
    archive_path: Path | None = None,
    input_dir: Path | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Extract and parse candidate entries from an archive ZIP or folder."""
    entries: list[tuple[str, dict[str, Any]]] = []

    if archive_path is not None:
        with ZipFile(archive_path) as archive:
            json_infos = [
                info
                for info in archive.infolist()
                if info.filename.endswith(".json")
                and not info.filename.endswith("EXPORT-REPORT.txt")
                and not info.is_dir()
            ]
            if len(json_infos) > MAX_ARCHIVE_ENTRIES:
                raise ValueError(
                    f"Archive exceeds maximum allowed entries "
                    f"({len(json_infos)} > {MAX_ARCHIVE_ENTRIES})"
                )
            total_size = sum(info.file_size for info in json_infos)
            if total_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"Archive exceeds maximum allowed uncompressed size "
                    f"({total_size} bytes > {MAX_TOTAL_UNCOMPRESSED_BYTES} bytes)"
                )
            for info in json_infos:
                if info.file_size > MAX_SINGLE_ENTRY_BYTES:
                    raise ValueError(
                        f"Entry {info.filename} exceeds maximum size "
                        f"({info.file_size} bytes > {MAX_SINGLE_ENTRY_BYTES} bytes)"
                    )
                raw = archive.read(info).decode("utf-8")
                entries.append((info.filename, json.loads(raw)))
    elif input_dir is not None:
        json_paths = [
            p
            for p in sorted(input_dir.rglob("*.json"))
            if not p.name.endswith("EXPORT-REPORT.txt")
        ]
        if len(json_paths) > MAX_ARCHIVE_ENTRIES:
            raise ValueError(
                f"Input directory exceeds maximum allowed entries "
                f"({len(json_paths)} > {MAX_ARCHIVE_ENTRIES})"
            )
        total_size = sum(p.stat().st_size for p in json_paths)
        if total_size > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError(
                f"Input directory exceeds maximum allowed uncompressed size "
                f"({total_size} bytes > {MAX_TOTAL_UNCOMPRESSED_BYTES} bytes)"
            )
        for path in json_paths:
            size = path.stat().st_size
            if size > MAX_SINGLE_ENTRY_BYTES:
                raise ValueError(
                    f"File {path.name} exceeds maximum size "
                    f"({size} bytes > {MAX_SINGLE_ENTRY_BYTES} bytes)"
                )
            raw = path.read_text(encoding="utf-8")
            entries.append((path.name, json.loads(raw)))
    else:
        raise ValueError("Must provide either archive_path or input_dir")

    return entries


def _process_existing_item(
    existing_path: Path,
    entry: dict[str, Any],
    loaded_entries: dict[Path, dict[str, Any]],
    *,
    dry_run: bool,
) -> tuple[bool, str]:
    """Merge incoming entry into existing file and save if changed."""
    existing = loaded_entries[existing_path]
    updated, changed, changes = merge_entry(existing, entry)
    if not changed:
        return False, ""

    validate_entry(updated)
    if not dry_run:
        existing_path.write_text(
            json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    loaded_entries[existing_path] = updated
    return True, f"BACKFILLED {existing_path.name}: {', '.join(changes)}"


def _process_new_item(
    entry: dict[str, Any],
    data_dir: Path,
    loaded_entries: dict[Path, dict[str, Any]],
    indices: tuple[
        dict[tuple[str, int], Path],
        dict[tuple[str, int], Path],
        dict[tuple[str, str], Path],
    ],
    *,
    dry_run: bool,
) -> str:
    """Create a new entry file and update indices."""
    by_tmdb, by_tvdb, by_imdb = indices
    target_path, new_entry = create_new_entry(entry, data_dir)

    if target_path in loaded_entries:
        raise ValueError(f"Target path already indexed - {target_path.name}")

    validate_entry(new_entry)
    if not dry_run:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(new_entry, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    loaded_entries[target_path] = new_entry
    m_type = new_entry["media_type"]
    if new_entry.get("tmdb_id") is not None:
        by_tmdb[(m_type, new_entry["tmdb_id"])] = target_path
    if new_entry.get("tvdb_id") is not None:
        by_tvdb[(m_type, new_entry["tvdb_id"])] = target_path
    if new_entry.get("imdb_id") is not None:
        by_imdb[(m_type, new_entry["imdb_id"])] = target_path

    return f"CREATED {target_path.name}: {new_entry['title']}"


def import_bulk_export(
    *,
    overture_dir: Path,
    archive_path: Path | None = None,
    input_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Merge bulk export items into OvertureDB dataset enforcing Rules 1 & 2."""
    data_dir = overture_dir / "data"
    by_tmdb, by_tvdb, by_imdb, loaded_entries = index_existing_entries(data_dir)
    indices = (by_tmdb, by_tvdb, by_imdb)

    incoming_entries = load_incoming_entries(
        archive_path=archive_path, input_dir=input_dir
    )

    created_count = 0
    backfilled_count = 0
    unchanged_count = 0
    skipped_count = 0
    errors: list[str] = []
    details: list[str] = []

    for name, raw_entry in incoming_entries:
        try:
            entry = validate_entry(raw_entry)
            existing_path = find_existing_entry(entry, by_tmdb, by_tvdb, by_imdb)

            if existing_path is not None:
                changed, detail = _process_existing_item(
                    existing_path, entry, loaded_entries, dry_run=dry_run
                )
                if changed:
                    backfilled_count += 1
                    details.append(detail)
                else:
                    unchanged_count += 1
            else:
                detail = _process_new_item(
                    entry, data_dir, loaded_entries, indices, dry_run=dry_run
                )
                created_count += 1
                details.append(detail)
        except (ValueError, StopIteration) as exc:
            errors.append(f"{name}: {exc}")
            skipped_count += 1

    # Validate the full catalog consistency for all loaded entries
    validate_entries(list(loaded_entries.values()))

    return {
        "total_incoming": len(incoming_entries),
        "created": created_count,
        "backfilled": backfilled_count,
        "unchanged": unchanged_count,
        "skipped": skipped_count,
        "errors": errors,
        "details": details,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Path to export ZIP archive")
    parser.add_argument(
        "--input-dir", type=Path, help="Path to unzipped input directory"
    )
    parser.add_argument(
        "--overture-dir",
        type=Path,
        default=Path(),
        help="Root path of OvertureDB repository",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate import without writing to disk",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    if not args.archive and not args.input_dir:
        parser.error("Specify either --archive or --input-dir")

    try:
        results = import_bulk_export(
            overture_dir=args.overture_dir,
            archive_path=args.archive,
            input_dir=args.input_dir,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    if args.json:
        print(json.dumps(results, indent=2))  # noqa: T201
        return 0 if not results["errors"] else 2

    mode = " (DRY RUN)" if results["dry_run"] else ""
    print(f"Bulk Import Results{mode}:")  # noqa: T201
    print(f"  Total incoming entries: {results['total_incoming']}")  # noqa: T201
    print(f"  New entries created:    {results['created']}")  # noqa: T201
    print(f"  Entries backfilled:     {results['backfilled']}")  # noqa: T201
    print(f"  Entries unchanged:      {results['unchanged']}")  # noqa: T201
    print(f"  Entries skipped/errors: {results['skipped']}")  # noqa: T201

    if results["errors"]:
        print("\nErrors / Collisions:")  # noqa: T201
        for err in results["errors"]:
            print(f"  - {err}")  # noqa: T201

    return 0 if not results["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
