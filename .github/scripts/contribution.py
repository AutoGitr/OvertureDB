"""Build, validate, and preview dataset contributions from GitHub issues."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "schema"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contract import validate_entry  # noqa: E402
from import_bulk_export import find_existing_entry, index_existing_entries  # noqa: E402

MODIFICATION_PLACEHOLDER = (
    "If this modifies an existing entry, replace this text with a reason "
    "for the change (e.g. higher resolution, textless, dead link, corrected ID)."
)


@dataclass
class ParsedContribution:
    media_type: str
    title: str
    year: int | None
    tmdb_id: int | None
    tvdb_id: int | None
    imdb_id: str | None
    poster_url: str | None
    background_url: str | None
    youtube_id: str | None
    seasons: list[dict[str, Any]]
    modification_reason: str | None


def clean_art_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    return re.sub(
        r"^(https?://(?:www\.)?theposterdb\.com/api/assets/\d+)/view/?$",
        r"\1",
        url,
    )


def extract_field(body: str, heading: str) -> str | None:
    lines = body.splitlines()
    target_heading = f"### {heading}".strip()
    capturing = False
    captured_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped == target_heading:
            capturing = True
            continue
        if capturing:
            if stripped.startswith("### "):
                break
            captured_lines.append(line)

    if not captured_lines:
        return None

    text = "\n".join(captured_lines).strip()
    if not text or text == "_No response_":
        return None
    return text


def _extract_media_type(issue_title: str, labels: list[str]) -> str:
    if "movie" in labels or issue_title.startswith("[Movie]:"):
        return "movie"
    if "show" in labels or issue_title.startswith("[Show]:"):
        return "show"
    raise ValueError("Issue must use the movie or show contribution form.")


def _parse_external_ids(
    body: str, media_type: str
) -> tuple[int | None, int | None, str | None]:
    tmdb_raw = extract_field(body, "TMDB ID")
    tmdb_id = None
    if tmdb_raw:
        tmdb_str = tmdb_raw.splitlines()[0].strip()
        if not re.match(r"^\d+$", tmdb_str):
            raise ValueError("TMDB ID must contain digits only.")
        tmdb_id = int(tmdb_str)

    tvdb_raw = extract_field(body, "TVDB ID")
    tvdb_id = None
    if tvdb_raw:
        tvdb_str = tvdb_raw.splitlines()[0].strip()
        if not re.match(r"^\d+$", tvdb_str):
            raise ValueError("TVDB ID must contain digits only.")
        tvdb_id = int(tvdb_str)

    imdb_raw = extract_field(body, "IMDb ID")
    imdb_id = None
    if imdb_raw:
        imdb_str = imdb_raw.splitlines()[0].strip()
        if not re.match(r"^tt\d+$", imdb_str):
            raise ValueError("IMDb ID must use the format tt followed by digits.")
        imdb_id = imdb_str

    if tmdb_id is None and tvdb_id is None and imdb_id is None:
        raise ValueError(
            f"{media_type.capitalize()} contributions need a TMDB, TVDB, or IMDb ID."
        )

    return tmdb_id, tvdb_id, imdb_id


def _parse_seasons(body: str, media_type: str) -> list[dict[str, Any]]:
    seasons: list[dict[str, Any]] = []
    seasons_raw = extract_field(body, "Season posters")
    if seasons_raw and media_type == "show":
        for line in seasons_raw.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            s_num_str, _, s_url = line.partition("=")
            s_num_str = s_num_str.strip()
            s_url = clean_art_url(s_url.strip())
            if not re.match(r"^\d+$", s_num_str) or not s_url:
                raise ValueError("Season posters must use season_num=url lines.")
            seasons.append({"season_num": int(s_num_str), "poster_url": s_url})
    return seasons


def parse_issue_form(
    body: str,
    issue_title: str,
    labels: list[str],
) -> ParsedContribution:
    media_type = _extract_media_type(issue_title, labels)

    title_raw = extract_field(body, "Title")
    if not title_raw:
        raise ValueError("Missing Title field.")
    title = title_raw.splitlines()[0].strip()

    year_raw = extract_field(body, "Year")
    year = None
    if year_raw:
        year_str = year_raw.splitlines()[0].strip()
        if not re.match(r"^\d{4}$", year_str):
            raise ValueError("Year must be a four-digit release year.")
        year = int(year_str)

    tmdb_id, tvdb_id, imdb_id = _parse_external_ids(body, media_type)

    poster_raw = extract_field(body, "Poster URL")
    poster_url = (
        clean_art_url(poster_raw.splitlines()[0].strip()) if poster_raw else None
    )

    bg_raw = extract_field(body, "Background URL")
    background_url = clean_art_url(bg_raw.splitlines()[0].strip()) if bg_raw else None

    yt_raw = extract_field(body, "YouTube theme video ID")
    youtube_id = yt_raw.splitlines()[0].strip() if yt_raw else None
    if youtube_id and not re.match(r"^[a-zA-Z0-9_-]{11}$", youtube_id):
        raise ValueError("YouTube video ID must be exactly 11 characters (not a URL).")

    seasons = _parse_seasons(body, media_type)

    reason_raw = extract_field(
        body, "Reason for modification (if replacing existing artwork or theme)"
    )
    modification_reason = reason_raw.strip() if reason_raw else None

    return ParsedContribution(
        media_type=media_type,
        title=title,
        year=year,
        tmdb_id=tmdb_id,
        tvdb_id=tvdb_id,
        imdb_id=imdb_id,
        poster_url=poster_url,
        background_url=background_url,
        youtube_id=youtube_id,
        seasons=seasons,
        modification_reason=modification_reason,
    )


def build_candidate_entry(parsed: ParsedContribution) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "media_type": parsed.media_type,
        "title": parsed.title,
        "year": parsed.year,
        "tmdb_id": parsed.tmdb_id,
        "tvdb_id": parsed.tvdb_id,
        "imdb_id": parsed.imdb_id,
        "poster_url": parsed.poster_url,
        "background_url": parsed.background_url,
        "youtube_id_overturedb": parsed.youtube_id,
        "youtube_id_themerrdb": None,
    }
    if parsed.media_type == "show":
        entry["seasons"] = parsed.seasons
    return entry


def determine_canonical_path(
    media_type: str,
    tmdb_id: int | None,
    tvdb_id: int | None,
    imdb_id: str | None,
    data_dir: Path,
) -> Path:
    folder = "movies" if media_type == "movie" else "shows"
    providers = (
        (
            ("tvdb", tvdb_id),
            ("tmdb", tmdb_id),
            ("imdb", imdb_id),
        )
        if media_type == "show"
        else (
            ("tmdb", tmdb_id),
            ("tvdb", tvdb_id),
            ("imdb", imdb_id),
        )
    )

    for prefix, val in providers:
        if val is not None:
            return data_dir / folder / f"{prefix}-{val}.json"

    raise ValueError(f"No valid identifier found to construct {media_type} filename.")


def _update_external_ids(updated: dict[str, Any], parsed: ParsedContribution) -> None:
    for id_field, val in (
        ("tmdb_id", parsed.tmdb_id),
        ("tvdb_id", parsed.tvdb_id),
        ("imdb_id", parsed.imdb_id),
    ):
        if val is not None:
            curr_val = updated.get(id_field)
            if curr_val is not None and curr_val != val:
                raise ValueError(
                    f"Conflicting {id_field}: existing={curr_val}, submitted={val}"
                )
            updated[id_field] = val


def _update_seasons(updated: dict[str, Any], seasons: list[dict[str, Any]]) -> None:
    if not seasons:
        return
    exist_seasons = {s["season_num"]: dict(s) for s in updated.get("seasons", [])}
    for s in seasons:
        exist_seasons[s["season_num"]] = {
            "season_num": s["season_num"],
            "poster_url": s["poster_url"],
        }
    updated["seasons"] = [exist_seasons[num] for num in sorted(exist_seasons.keys())]


def is_media_replacement(
    existing: dict[str, Any],
    parsed: ParsedContribution,
) -> bool:
    """Check if contribution replaces existing non-null artwork or active theme."""
    old_poster = existing.get("poster_url")
    if (
        old_poster
        and parsed.poster_url
        and parsed.poster_url.strip() != old_poster.strip()
    ):
        return True

    old_bg = existing.get("background_url")
    if (
        old_bg
        and parsed.background_url
        and parsed.background_url.strip() != old_bg.strip()
    ):
        return True

    old_yt = existing.get("youtube_id_overturedb")
    if old_yt and parsed.youtube_id and parsed.youtube_id.strip() != old_yt.strip():
        return True

    if parsed.media_type == "show" and parsed.seasons:
        exist_seasons = {
            s["season_num"]: s.get("poster_url")
            for s in (existing.get("seasons") or [])
            if "season_num" in s and s.get("poster_url")
        }
        for s in parsed.seasons:
            s_num = s.get("season_num")
            s_poster = s.get("poster_url")
            old_s_poster = exist_seasons.get(s_num)
            if old_s_poster and s_poster and s_poster.strip() != old_s_poster.strip():
                return True

    return False


def _update_entry(
    existing_entry: dict[str, Any],
    parsed: ParsedContribution,
    rel_path: str,
) -> tuple[dict[str, Any], str]:
    orig_content = json.dumps(existing_entry, indent=2, ensure_ascii=False) + "\n"
    updated = dict(existing_entry)
    updated["title"] = parsed.title
    if parsed.year is not None:
        updated["year"] = parsed.year

    _update_external_ids(updated, parsed)

    if parsed.poster_url:
        updated["poster_url"] = parsed.poster_url
    if parsed.background_url:
        updated["background_url"] = parsed.background_url
    if parsed.youtube_id:
        if parsed.youtube_id == updated.get("youtube_id_themerrdb"):
            updated["youtube_id_overturedb"] = None
        else:
            updated["youtube_id_overturedb"] = parsed.youtube_id

    if parsed.media_type == "show":
        _update_seasons(updated, parsed.seasons)

    validated = validate_entry(updated)
    new_content = json.dumps(validated, indent=2, ensure_ascii=False) + "\n"
    diff_lines = difflib.unified_diff(
        orig_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
    )
    return validated, "".join(diff_lines)


def format_media_comparison(
    existing: dict[str, Any],
    updated: dict[str, Any],
) -> str:
    """Format markdown comparing changed artwork and theme fields."""
    lines: list[str] = []

    old_poster = existing.get("poster_url")
    new_poster = updated.get("poster_url")
    if old_poster != new_poster:
        old_val = f"[View image]({old_poster})" if old_poster else "_None_"
        new_val = f"[View image]({new_poster})" if new_poster else "_None_"
        lines.append(f"- **Old Poster:** {old_val}")
        lines.append(f"- **New Poster:** {new_val}")

    old_bg = existing.get("background_url")
    new_bg = updated.get("background_url")
    if old_bg != new_bg:
        old_val = f"[View image]({old_bg})" if old_bg else "_None_"
        new_val = f"[View image]({new_bg})" if new_bg else "_None_"
        lines.append(f"- **Old Background:** {old_val}")
        lines.append(f"- **New Background:** {new_val}")

    old_yt = existing.get("youtube_id_overturedb")
    new_yt = updated.get("youtube_id_overturedb")
    if old_yt and old_yt != new_yt:
        old_val = (
            f"[Watch video](https://www.youtube.com/watch?v={old_yt}) (`{old_yt}`)"
        )
        new_val = (
            f"[Watch video](https://www.youtube.com/watch?v={new_yt}) (`{new_yt}`)"
            if new_yt
            else "_None_"
        )
        lines.append(f"- **Old YouTube Theme:** {old_val}")
        lines.append(f"- **New YouTube Theme:** {new_val}")

    exist_seasons = {
        s["season_num"]: s.get("poster_url")
        for s in existing.get("seasons", [])
        if "season_num" in s
    }
    updated_seasons = {
        s["season_num"]: s.get("poster_url")
        for s in updated.get("seasons", [])
        if "season_num" in s
    }
    for s_num in sorted(set(exist_seasons) | set(updated_seasons)):
        old_s = exist_seasons.get(s_num)
        new_s = updated_seasons.get(s_num)
        if old_s != new_s:
            old_val = f"[View image]({old_s})" if old_s else "_None_"
            new_val = f"[View image]({new_s})" if new_s else "_None_"
            lines.append(f"- **Old Season {s_num} Poster:** {old_val}")
            lines.append(f"- **New Season {s_num} Poster:** {new_val}")

    return "\n".join(lines)


def process_contribution(
    parsed: ParsedContribution,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    data_dir = repo_root / "data"
    by_tmdb, by_tvdb, by_imdb, loaded_entries = index_existing_entries(data_dir)

    candidate = build_candidate_entry(parsed)
    existing_path = find_existing_entry(candidate, by_tmdb, by_tvdb, by_imdb)

    media_comparison = ""
    if existing_path is not None:
        target_path = existing_path
        target_rel = target_path.relative_to(repo_root).as_posix()
        existing_entry = dict(loaded_entries[existing_path])
        is_modification = is_media_replacement(existing_entry, parsed)
        if is_modification:
            reason = parsed.modification_reason
            if not reason or reason.strip().lower() == MODIFICATION_PLACEHOLDER.lower():
                raise ValueError(
                    f"Existing artwork or theme is being replaced in `{target_rel}`. "
                    "To modify an existing entry, please edit the issue description "
                    "and replace the placeholder in 'Reason for modification' with an "
                    "explanation of your changes."
                )
        validated, diff = _update_entry(existing_entry, parsed, target_rel)
        if is_modification:
            media_comparison = format_media_comparison(existing_entry, validated)
    else:
        target_path = determine_canonical_path(
            parsed.media_type,
            parsed.tmdb_id,
            parsed.tvdb_id,
            parsed.imdb_id,
            data_dir,
        )
        target_rel = target_path.relative_to(repo_root).as_posix()
        validated = validate_entry(candidate)
        is_modification = False
        new_content = json.dumps(validated, indent=2, ensure_ascii=False) + "\n"
        diff_lines = difflib.unified_diff(
            [],
            new_content.splitlines(keepends=True),
            fromfile="/dev/null",
            tofile=f"b/{target_rel}",
        )
        diff = "".join(diff_lines)

    new_content = json.dumps(validated, indent=2, ensure_ascii=False) + "\n"
    if not dry_run:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(new_content, encoding="utf-8", newline="\n")

    return {
        "status": "ok",
        "target": target_rel,
        "is_modification": is_modification,
        "is_addition": existing_path is not None and not is_modification,
        "modification_reason": parsed.modification_reason if is_modification else None,
        "diff": diff,
        "media_comparison": media_comparison,
        "media_type": validated["media_type"],
        "title": validated["title"],
        "year": validated.get("year"),
        "tmdb_id": validated.get("tmdb_id"),
        "tvdb_id": validated.get("tvdb_id"),
        "imdb_id": validated.get("imdb_id"),
        "youtube_id": (
            validated.get("youtube_id_overturedb")
            or validated.get("youtube_id_themerrdb")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issue-body-file",
        type=Path,
        required=True,
        help="Path to file containing issue body markdown",
    )
    parser.add_argument("--issue-title", required=True, help="Issue title string")
    parser.add_argument(
        "--labels-file",
        type=Path,
        required=True,
        help="Path to file containing issue labels (one per line)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(),
        help="Root path of OvertureDB repository",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate without writing files to disk",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON result",
    )

    args = parser.parse_args()

    try:
        body = args.issue_body_file.read_text(encoding="utf-8-sig")
        labels = [
            line.strip()
            for line in args.labels_file.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()
        ]

        parsed = parse_issue_form(body, args.issue_title, labels)
        result = process_contribution(parsed, args.repo_root, dry_run=args.dry_run)

        if args.json:
            print(json.dumps(result, indent=2))  # noqa: T201
        else:
            print(result["target"])  # noqa: T201
        return 0
    except Exception as exc:
        if args.json:
            print(  # noqa: T201
                json.dumps({"status": "error", "error": str(exc)}, indent=2)
            )
        else:
            print(f"Error: {exc}", file=sys.stderr)  # noqa: T201
        return 1


if __name__ == "__main__":
    sys.exit(main())
