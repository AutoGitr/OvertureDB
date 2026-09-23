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


def _first_non_empty_line(val: str | None) -> str | None:
    if not val:
        return None
    for line in val.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def clean_art_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url or url == "_No response_":
        return None
    # Strip quotes
    if (url.startswith('"') and url.endswith('"')) or (
        url.startswith("'") and url.endswith("'")
    ):
        url = url[1:-1].strip()
    # Strip angle brackets <url>
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1].strip()
    # Extract from markdown link [text](url)
    md_match = re.match(r"^\[.*?\]\(\s*(https?://[^\s)]+)\s*\)$", url)
    if md_match:
        url = md_match.group(1).strip()
    # Upgrade http to https
    if url.startswith("http://"):
        url = "https://" + url[7:]
    # Strip fragment #...
    url = url.split("#")[0].strip()
    # Normalize ThePosterDB poster web URL to API asset URL
    url = re.sub(
        r"^(https?://(?:www\.)?theposterdb\.com/)poster/(\d+)/?$",
        r"\1api/assets/\2",
        url,
    )
    # Strip /view or trailing slash from ThePosterDB API assets
    url = re.sub(
        r"^(https?://(?:www\.)?theposterdb\.com/api/assets/\d+)(?:/view)?/?$",
        r"\1",
        url,
    )
    return url or None


def clean_youtube_id(raw_id: str | None) -> str | None:
    if not raw_id:
        return None
    val = raw_id.strip()
    if not val or val == "_No response_":
        return None

    # Strip quotes and angle brackets
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        val = val[1:-1].strip()
    if val.startswith("<") and val.endswith(">"):
        val = val[1:-1].strip()

    # Full YouTube URLs across domains: youtu.be, watch?v=, embed/, shorts/
    yt_url_match = re.search(
        r"(?:youtu\.be/|(?:[a-zA-Z0-9-]+\.)?youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/))([a-zA-Z0-9_-]{11})",
        val,
    )
    if yt_url_match:
        return yt_url_match.group(1)

    if re.match(r"^[a-zA-Z0-9_-]{11}$", val):
        return val

    raise ValueError(
        f"Invalid YouTube theme ID or URL: '{val}'. "
        "Expected an 11-character video ID or YouTube URL."
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
    title_lower = issue_title.lower()
    if "movie" in labels or title_lower.startswith("[movie"):
        return "movie"
    if "show" in labels or title_lower.startswith("[show"):
        return "show"
    raise ValueError("Issue must use the movie or show contribution form.")


def _parse_external_ids(
    body: str, media_type: str
) -> tuple[int | None, int | None, str | None]:
    tmdb_raw = extract_field(body, "TMDB ID")
    tmdb_id = None
    if tmdb_raw:
        tmdb_str = _first_non_empty_line(tmdb_raw) or ""
        tmdb_url_match = re.search(r"themoviedb\.org/(?:movie|tv)/(\d+)", tmdb_str)
        if tmdb_url_match:
            tmdb_id = int(tmdb_url_match.group(1))
        elif not re.match(r"^\d+$", tmdb_str):
            raise ValueError("TMDB ID must contain digits only.")
        elif int(tmdb_str) < 1:
            raise ValueError("TMDB ID must be a positive integer.")
        else:
            tmdb_id = int(tmdb_str)

    tvdb_raw = extract_field(body, "TVDB ID")
    tvdb_id = None
    if tvdb_raw:
        tvdb_str = _first_non_empty_line(tvdb_raw) or ""
        tvdb_url_match = re.search(
            r"thetvdb\.com/(?:dereferrer/)?(?:series|movie)s?/(\d+)", tvdb_str
        )
        if tvdb_url_match:
            tvdb_id = int(tvdb_url_match.group(1))
        elif not re.match(r"^\d+$", tvdb_str):
            raise ValueError("TVDB ID must contain digits only.")
        elif int(tvdb_str) < 1:
            raise ValueError("TVDB ID must be a positive integer.")
        else:
            tvdb_id = int(tvdb_str)

    imdb_raw = extract_field(body, "IMDb ID")
    imdb_id = None
    if imdb_raw:
        imdb_str = _first_non_empty_line(imdb_raw) or ""
        imdb_match = re.search(r"(tt\d+)", imdb_str, flags=re.IGNORECASE)
        if not imdb_match:
            raise ValueError("IMDb ID must use the format tt followed by digits.")
        imdb_id = imdb_match.group(1).lower()

    if tmdb_id is None and tvdb_id is None and imdb_id is None:
        raise ValueError(
            f"{media_type.capitalize()} contributions need a TMDB, TVDB, or IMDb ID."
        )

    return tmdb_id, tvdb_id, imdb_id


def _parse_seasons(body: str, media_type: str) -> list[dict[str, Any]]:
    seasons_raw = extract_field(body, "Season posters")
    if seasons_raw and media_type == "movie":
        raise ValueError("Season posters cannot be added to a movie.")

    seasons: list[dict[str, Any]] = []
    if seasons_raw and media_type == "show":
        seen_seasons: set[int] = set()
        for line in seasons_raw.splitlines():
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^(?:[-*•]|\d+\.)\s*", "", line).strip()
            if not line:
                continue
            if "=" not in line:
                raise ValueError(
                    f"Season poster line must use format season_num=url: '{line}'"
                )
            s_num_str, _, s_url = line.partition("=")
            s_num_str = s_num_str.strip()
            s_num_clean = re.sub(
                r"^(?:season|s)\s*", "", s_num_str, flags=re.IGNORECASE
            ).strip()
            if s_num_clean.lower() in ("specials", "special"):
                s_num = 0
            elif re.match(r"^\d+$", s_num_clean):
                s_num = int(s_num_clean)
            else:
                raise ValueError(
                    f"Invalid season number '{s_num_str}' in line: '{line}'"
                )

            s_url = clean_art_url(s_url.strip())
            if not s_url:
                raise ValueError(
                    f"Missing or invalid artwork URL in season poster line: '{line}'"
                )

            if s_num in seen_seasons:
                raise ValueError(f"Duplicate season number in submission: {s_num}")
            seen_seasons.add(s_num)

            seasons.append({"season_num": s_num, "poster_url": s_url})
    return seasons


def parse_issue_form(
    body: str,
    issue_title: str,
    labels: list[str],
) -> ParsedContribution:
    media_type = _extract_media_type(issue_title, labels)

    title_raw = extract_field(body, "Title")
    title = _first_non_empty_line(title_raw)
    if not title:
        raise ValueError("Missing Title field.")

    year_raw = extract_field(body, "Year")
    year = None
    year_line = _first_non_empty_line(year_raw)
    if year_line:
        if not re.match(r"^\d{4}$", year_line) or int(year_line) < 1000:
            raise ValueError("Year must be a four-digit release year.")
        year = int(year_line)

    tmdb_id, tvdb_id, imdb_id = _parse_external_ids(body, media_type)

    poster_raw = extract_field(body, "Poster URL")
    poster_url = clean_art_url(_first_non_empty_line(poster_raw))

    bg_raw = extract_field(body, "Background URL")
    background_url = clean_art_url(_first_non_empty_line(bg_raw))

    yt_raw = extract_field(body, "YouTube theme video ID")
    youtube_id = clean_youtube_id(_first_non_empty_line(yt_raw))

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
    exist_seasons = {
        s["season_num"]: dict(s)
        for s in (updated.get("seasons") or [])
        if isinstance(s, dict) and "season_num" in s
    }
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
    themerr_yt = (existing.get("youtube_id_themerrdb") or "").strip()
    if (
        old_yt
        and parsed.youtube_id
        and parsed.youtube_id.strip() != old_yt.strip()
        and parsed.youtube_id.strip() != themerr_yt
    ):
        return True

    if parsed.media_type == "show" and parsed.seasons:
        exist_seasons = {
            s["season_num"]: s.get("poster_url")
            for s in (existing.get("seasons") or [])
            if isinstance(s, dict) and "season_num" in s and s.get("poster_url")
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
    if parsed.youtube_id and parsed.youtube_id != updated.get("youtube_id_themerrdb"):
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
    """Format markdown comparing changed artwork and theme fields inline."""
    lines: list[str] = []

    old_poster = existing.get("poster_url")
    new_poster = updated.get("poster_url")
    if old_poster != new_poster:
        old_val = f"[Old]({old_poster})" if old_poster else "_None_"
        new_val = f"[New]({new_poster})" if new_poster else "_None_"
        lines.append(f"- **Poster:** {old_val} | {new_val}")

    old_bg = existing.get("background_url")
    new_bg = updated.get("background_url")
    if old_bg != new_bg:
        old_val = f"[Old]({old_bg})" if old_bg else "_None_"
        new_val = f"[New]({new_bg})" if new_bg else "_None_"
        lines.append(f"- **Background:** {old_val} | {new_val}")

    old_yt = existing.get("youtube_id_overturedb")
    new_yt = updated.get("youtube_id_overturedb")
    if old_yt and old_yt != new_yt:
        old_val = (
            f"[Old](https://www.youtube.com/watch?v={old_yt})" if old_yt else "_None_"
        )
        new_val = (
            f"[New](https://www.youtube.com/watch?v={new_yt})" if new_yt else "_None_"
        )
        lines.append(f"- **YouTube Theme:** {old_val} | {new_val}")

    exist_seasons = {
        s["season_num"]: s.get("poster_url")
        for s in (existing.get("seasons") or [])
        if isinstance(s, dict) and "season_num" in s
    }
    updated_seasons = {
        s["season_num"]: s.get("poster_url")
        for s in (updated.get("seasons") or [])
        if isinstance(s, dict) and "season_num" in s
    }
    for s_num in sorted(set(exist_seasons) | set(updated_seasons)):
        old_s = exist_seasons.get(s_num)
        new_s = updated_seasons.get(s_num)
        if old_s != new_s:
            old_val = f"[Old]({old_s})" if old_s else "_None_"
            new_val = f"[New]({new_s})" if new_s else "_None_"
            lines.append(f"- **Season {s_num} Poster:** {old_val} | {new_val}")

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

    has_media = bool(
        parsed.poster_url
        or parsed.background_url
        or parsed.youtube_id
        or parsed.seasons
    )
    if existing_path is None and not has_media:
        raise ValueError(
            "New entry contributions must include at least one artwork URL "
            "(poster, background, or season poster) or YouTube theme ID."
        )

    media_comparison = ""
    if existing_path is not None:
        target_path = existing_path
        target_rel = target_path.relative_to(repo_root).as_posix()
        existing_entry = dict(loaded_entries[existing_path])
        is_modification = is_media_replacement(existing_entry, parsed)
        if is_modification:
            reason = parsed.modification_reason
            clean_reason = reason.strip().strip("\"'").strip() if reason else ""
            placeholder_clean = (
                MODIFICATION_PLACEHOLDER.strip().strip("\"'").strip().lower()
            )
            if (
                not clean_reason
                or clean_reason.lower() == placeholder_clean
                or clean_reason.lower() in ("_no response_", "none", "n/a")
            ):
                raise ValueError(
                    f"Existing artwork or theme is being replaced in `{target_rel}`. "
                    "To modify an existing entry, please edit the issue description "
                    "and replace the placeholder in 'Reason for modification' with an "
                    "explanation of your changes."
                )
        validated, diff = _update_entry(existing_entry, parsed, target_rel)
        if not diff.strip():
            themerr_id = existing_entry.get("youtube_id_themerrdb")
            if parsed.youtube_id and parsed.youtube_id == themerr_id:
                raise ValueError(
                    f"No changes or additions detected for `{target_rel}`. "
                    "The submitted YouTube theme is already active via ThemerrDB, "
                    "and no other fields were modified."
                )
            raise ValueError(
                f"No changes or additions detected for `{target_rel}`. "
                "All submitted values match the existing entry."
            )
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
