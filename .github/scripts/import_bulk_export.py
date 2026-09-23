"""Backfill bulk selections without replacing curated media or imported themes."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from catalog import art_urls, check_art_destination, dataset, write_changes

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


@dataclass
class ReviewItem:
    title: str
    year: int | None
    media_type: str
    poster_url: str | None = None
    background_url: str | None = None
    youtube_id: str | None = None
    seasons: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])


def format_review_markdown(review_items: list[ReviewItem]) -> str:
    """Render collapsible, alphabetically sorted review section with clickable links."""
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
    for item in sorted_items:
        year_str = f" ({item.year})" if item.year else ""
        title = escape(item.title).replace("\n", " ").replace("\r", " ")
        title = title.replace("@", "&#64;").replace("[", "&#91;")
        lines.append(f"#### {title}{year_str}")
        if item.poster_url:
            lines.append(f"- **Poster:** [View image](<{escape(item.poster_url)}>)")
        if item.background_url:
            lines.append(
                f"- **Background:** [View image](<{escape(item.background_url)}>)"
            )
        if item.youtube_id:
            yt_url = f"https://www.youtube.com/watch?v={item.youtube_id}"
            lines.append(
                f"- **YouTube Theme:** [Watch video]({yt_url}) (`{item.youtube_id}`)"
            )
        for s_num, s_url in sorted(item.seasons, key=lambda s: s[0]):
            lines.append(
                f"- **Season {s_num} Poster:** [View image](<{escape(s_url)}>)"
            )
        lines.append("")

    lines.append("</details>")
    return "\n".join(lines)


def index_existing_entries(data_dir: Path) -> ExistingIndex:
    """Index existing OvertureDB entries by TMDB, TVDB, and IMDb identities."""
    by_tmdb: dict[tuple[str, int], Path] = {}
    by_tvdb: dict[tuple[str, int], Path] = {}
    by_imdb: dict[tuple[str, str], Path] = {}
    loaded: dict[Path, dict[str, Any]] = {}

    if not data_dir.is_dir():
        raise ValueError(f"Dataset directory does not exist: {data_dir}")

    paths = sorted(data_dir.rglob("*.json"))
    for path, entry in zip(paths, dataset(data_dir.parent), strict=True):
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
            for info in json_infos:
                raw = archive.read(info).decode("utf-8")
                entries.append((info.filename, json.loads(raw)))
    elif input_dir is not None:
        if not input_dir.is_dir():
            raise ValueError(f"Input directory does not exist: {input_dir}")
        json_paths = sorted(input_dir.rglob("*.json"))
        _check_sizes([(p.name, p.stat().st_size) for p in json_paths])
        for path in json_paths:
            raw = path.read_text(encoding="utf-8")
            entries.append((path.name, json.loads(raw)))
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
) -> ReviewItem | None:
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

    if backfilled_poster or backfilled_bg or backfilled_yt or backfilled_seasons:
        return ReviewItem(
            title=updated["title"],
            year=updated.get("year"),
            media_type=updated["media_type"],
            poster_url=backfilled_poster,
            background_url=backfilled_bg,
            youtube_id=backfilled_yt,
            seasons=backfilled_seasons,
        )
    return None


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
        )
    return None


def _process_existing_item(
    existing_path: Path,
    entry: dict[str, Any],
    loaded_entries: dict[Path, dict[str, Any]],
) -> tuple[bool, str, ReviewItem | None]:
    """Plan a backfill without writing files."""
    existing = loaded_entries[existing_path]
    updated, changed, changes = merge_entry(existing, entry)
    if not changed:
        return False, "", None

    validate_entry(updated)
    loaded_entries[existing_path] = updated
    review_item = _collect_backfilled_review(existing, updated)
    return True, f"BACKFILLED {existing_path.name}: {', '.join(changes)}", review_item


def _process_new_item(
    entry: dict[str, Any],
    data_dir: Path,
    loaded_entries: dict[Path, dict[str, Any]],
    indices: tuple[
        dict[tuple[str, int], Path],
        dict[tuple[str, int], Path],
        dict[tuple[str, str], Path],
    ],
) -> tuple[str, ReviewItem | None]:
    """Create a new entry file and update indices."""
    by_tmdb, by_tvdb, by_imdb = indices
    target_path, new_entry = create_new_entry(entry, data_dir)

    if target_path in loaded_entries:
        raise ValueError(f"Target path already indexed - {target_path.name}")

    validate_entry(new_entry)
    review_item = _collect_new_review(new_entry)
    if review_item is None:
        raise ValueError("New bulk entries must include artwork or an OvertureDB theme")

    loaded_entries[target_path] = new_entry
    m_type = new_entry["media_type"]
    if new_entry.get("tmdb_id") is not None:
        by_tmdb[(m_type, new_entry["tmdb_id"])] = target_path
    if new_entry.get("tvdb_id") is not None:
        by_tvdb[(m_type, new_entry["tvdb_id"])] = target_path
    if new_entry.get("imdb_id") is not None:
        by_imdb[(m_type, new_entry["imdb_id"])] = target_path

    return f"CREATED {target_path.name}: {new_entry['title']}", review_item


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
    original_entries = dict(loaded_entries)
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
    review_items: list[ReviewItem] = []

    for name, raw_entry in incoming_entries:
        try:
            entry = validate_entry(raw_entry)
            for url in art_urls([entry]):
                check_art_destination(url, resolve=False)
            existing_path = find_existing_entry(entry, by_tmdb, by_tvdb, by_imdb)

            if existing_path is not None:
                changed, detail, review = _process_existing_item(
                    existing_path, entry, loaded_entries
                )
                updated = loaded_entries[existing_path]
                for provider, index in zip(
                    ("tmdb", "tvdb", "imdb"), indices, strict=True
                ):
                    if updated[f"{provider}_id"] is not None:
                        index[(updated["media_type"], updated[f"{provider}_id"])] = (
                            existing_path
                        )
                if changed:
                    backfilled_count += 1
                    details.append(detail)
                    if review:
                        review_items.append(review)
                else:
                    unchanged_count += 1
            else:
                detail, review = _process_new_item(
                    entry, data_dir, loaded_entries, indices
                )
                created_count += 1
                details.append(detail)
                if review:
                    review_items.append(review)
        except (ValueError, StopIteration) as exc:
            errors.append(f"{name}: {exc}")
            skipped_count += 1

    # Validate the full catalog consistency for all loaded entries
    validate_entries(list(loaded_entries.values()))
    if not dry_run and not errors:
        write_changes(original_entries, loaded_entries, overture_dir)

    return {
        "total_incoming": len(incoming_entries),
        "created": created_count,
        "backfilled": backfilled_count,
        "unchanged": unchanged_count,
        "skipped": skipped_count,
        "errors": errors,
        "details": details,
        "review_markdown": format_review_markdown(review_items),
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--archive", type=Path, help="Path to export ZIP archive")
    source.add_argument(
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
    parser.add_argument(
        "--review-markdown",
        action="store_true",
        help="Output review markdown section with clickable art and theme URLs",
    )
    args = parser.parse_args()

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

    if args.review_markdown:
        if results["review_markdown"]:
            print(results["review_markdown"])  # noqa: T201
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
