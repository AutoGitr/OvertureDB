"""Build, validate, and preview dataset contributions from GitHub issues."""

lazy import difflib
lazy import json
lazy import re
lazy from dataclasses import dataclass
lazy from pathlib import Path
lazy from typing import Any
lazy from urllib.parse import quote

lazy from schema.contract import (
    IDENTITY_FIELDS,
    MAX_EXTERNAL_ID,
    catalog_art_url,
    validate_entry,
)

lazy from .catalog import (
    EntryIndex,
    entry_json,
    entry_path,
    new_entry,
    write_entry_json,
)
lazy from .import_themerrdb import extract_youtube_id

ROOT = Path(__file__).resolve().parents[1]
#: What GitHub writes under a heading whose issue form field was left empty.
NO_RESPONSE = "_No response_"


class NoChangesError(ValueError):
    """The contribution's values are already in the dataset."""


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
    remove: bool = False


def _first_non_empty_line(val: str | None) -> str | None:
    if not val:
        return None
    for line in val.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def clean_art_url(raw_url: str | None) -> str | None:
    """Unwrap a submitted artwork link and return its canonical form.

    Raises:
        ValueError: When the link is not catalog artwork.
    """
    url = unwrap(raw_url)
    return catalog_art_url(url) if url else None


def unwrap(raw: str | None) -> str | None:
    """Return a submitted value without the quotes, angle brackets or Markdown
    link around it, or ``None`` when the field was left empty.
    """
    value = (raw or "").strip()
    if not value or value == NO_RESPONSE:
        return None
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    if markdown := re.fullmatch(r"\[[^\]]*\]\(\s*(https?://[^\s)]+)\s*\)", value):
        value = markdown[1]
    return value or None


def clean_youtube_id(raw_id: str | None) -> str | None:
    val = unwrap(raw_id)
    if val is None:
        return None

    # Full YouTube URLs across domains: youtu.be, watch?v=, embed/, shorts/
    video_id = extract_youtube_id(val)
    if video_id:
        return video_id

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
    if not text or text == NO_RESPONSE:
        return None
    return text


def _extract_media_type(issue_title: str, labels: list[str]) -> str:
    media_labels = set(labels) & {"movie", "show", "bulk"}
    if len(media_labels) != 1 or "bulk" in media_labels:
        raise ValueError("Issue must have exactly one movie or show label.")
    return media_labels.pop()


def _numeric_id(body: str, provider: str, url_pattern: str) -> int | None:
    raw = _first_non_empty_line(extract_field(body, f"{provider} ID"))
    if raw is None:
        return None
    match = re.fullmatch(r"https?://(?:www\.)?" + url_pattern + r"/?(?:\?[^\s]*)?", raw)
    digits = match[1] if match else raw
    if not re.fullmatch(r"[0-9]+", digits):
        raise ValueError(
            f"{provider} ID must contain digits only or a valid {provider} URL."
        )
    value = int(digits)
    if not 0 < value <= MAX_EXTERNAL_ID:
        raise ValueError(f"{provider} ID must be a positive integer below 2^63.")
    return value


def _parse_external_ids(
    body: str, media_type: str
) -> tuple[int | None, int | None, str | None]:
    tmdb_id = _numeric_id(
        body, "TMDB", r"themoviedb\.org/(?:movie|tv)/([0-9]+)(?:-[^/?#\s]+)?"
    )
    tvdb_id = _numeric_id(
        body, "TVDB", r"thetvdb\.com/(?:dereferrer/)?(?:series|movies?)/([0-9]+)"
    )
    imdb_raw = _first_non_empty_line(extract_field(body, "IMDb ID"))
    imdb_id = None
    if imdb_raw:
        match = re.fullmatch(
            r"(?:https?://(?:www\.)?imdb\.com/title/)?(tt[0-9]+)(?:/)?(?:\?[^\s]*)?",
            imdb_raw,
            flags=re.IGNORECASE,
        )
        if not match:
            raise ValueError(
                "IMDb ID must use the format tt followed by digits "
                "or an IMDb title URL."
            )
        imdb_id = match[1].lower()

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
            if s_num_clean.lower() in {"specials", "special"}:
                s_num = 0
            elif re.fullmatch(r"\d+", s_num_clean):
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
        if not re.fullmatch(r"\d{4}", year_line) or int(year_line) < 1000:
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

    reason_raw = extract_field(body, "Reason for modification")
    modification_reason = reason_raw.strip() if reason_raw else None
    remove = bool(re.search(r"- \[x\]", extract_field(body, "Removal") or "", re.I))

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
        remove=remove,
    )


def reason_text(reason: str | None) -> str:
    """Return the explanation, treating empty form responses as absent."""
    text = (reason or "").strip().strip("\"'").strip()
    return "" if text.lower() in {NO_RESPONSE.lower(), "none", "n/a"} else text


def build_candidate_entry(parsed: ParsedContribution) -> dict[str, Any]:
    entry = new_entry(
        parsed.media_type,
        parsed.title,
        year=parsed.year,
        tmdb_id=parsed.tmdb_id,
        tvdb_id=parsed.tvdb_id,
        imdb_id=parsed.imdb_id,
        poster_url=parsed.poster_url,
        background_url=parsed.background_url,
        youtube_id_overturedb=parsed.youtube_id,
    )
    if parsed.media_type == "show":
        entry["seasons"] = parsed.seasons
    return entry


def _update_seasons(updated: dict[str, Any], seasons: list[dict[str, Any]]) -> None:
    if not seasons:
        return
    seasons_before: list[dict[str, Any]] = updated.get("seasons", [])
    exist_seasons = {s["season_num"]: dict(s) for s in seasons_before}
    for s in seasons:
        exist_seasons[s["season_num"]] = {
            "season_num": s["season_num"],
            "poster_url": s["poster_url"],
        }
    updated["seasons"] = [exist_seasons[num] for num in sorted(exist_seasons.keys())]


def is_replacement(
    existing: dict[str, Any],
    parsed: ParsedContribution,
) -> bool:
    """Check if the contribution replaces metadata, an identifier, artwork or theme."""
    if parsed.title != existing["title"]:
        return True
    if (
        existing["year"] is not None
        and parsed.year is not None
        and parsed.year != existing["year"]
    ):
        return True
    for field in IDENTITY_FIELDS:
        new = getattr(parsed, field)
        if existing[field] is not None and new is not None and new != existing[field]:
            return True
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
        seasons_before: list[dict[str, Any]] = existing.get("seasons", [])
        exist_seasons = {
            s["season_num"]: s.get("poster_url")
            for s in seasons_before
            if s.get("poster_url")
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

    for field in IDENTITY_FIELDS:
        if (value := getattr(parsed, field)) is not None:
            updated[field] = value

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


def _remove_entry(
    parsed: ParsedContribution,
    index: EntryIndex,
    existing_path: Path | None,
    repo_root: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    if existing_path is None:
        raise ValueError("Removal needs the identifiers of an existing entry.")
    target_rel = existing_path.relative_to(repo_root).as_posix()
    if not reason_text(parsed.modification_reason):
        raise ValueError(
            f"Removing `{target_rel}` needs a reason: edit the issue and explain "
            "why in 'Reason for modification'."
        )
    existing_entry = index.entries[existing_path]
    diff = "".join(
        difflib.unified_diff(
            entry_json(existing_entry).splitlines(keepends=True),
            [],
            fromfile=f"a/{target_rel}",
            tofile="/dev/null",
        )
    )
    if not dry_run:
        existing_path.unlink()
    return {
        "status": "ok",
        "entry": None,
        "previous": existing_entry,
        "removed": True,
        "target": target_rel,
        "previous_target": target_rel,
        "is_modification": True,
        "is_addition": False,
        "modification_reason": parsed.modification_reason,
        "diff": diff,
        "media_comparison": format_media_comparison(existing_entry, {}),
    }


def format_media_comparison(
    existing: dict[str, Any],
    updated: dict[str, Any],
) -> str:
    """Format markdown comparing changed artwork and theme fields inline."""

    def selections(entry: dict[str, Any]) -> dict[str, str | None]:
        theme = entry.get("youtube_id_overturedb")
        values = {
            "Poster": entry.get("poster_url"),
            "Background": entry.get("background_url"),
            "YouTube Theme": f"https://www.youtube.com/watch?v={theme}"
            if theme
            else None,
        }
        for season in entry.get("seasons", []):
            values[f"Season {season['season_num']} Poster"] = season["poster_url"]
        return values

    old, new = selections(existing), selections(updated)
    lines: list[str] = []
    for label in dict.fromkeys([*old, *new]):
        before, after = old.get(label), new.get(label)
        if before == after:
            continue
        links = [
            f"[{name}]({quote(url, safe='/:?=&%#+,.-_~')})" if url else "_None_"
            for name, url in (("Old", before), ("New", after))
        ]
        lines.append(f"- **{label}:** {' | '.join(links)}")
    return "\n".join(lines)


def process_contribution(
    parsed: ParsedContribution,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    index = EntryIndex.load(repo_root)
    candidate = build_candidate_entry(parsed)
    existing_path = index.find(candidate)
    if parsed.remove:
        return _remove_entry(parsed, index, existing_path, repo_root, dry_run=dry_run)

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
    existing_entry: dict[str, Any] | None = None
    previous_target: str | None = None
    if existing_path is not None:
        target_rel = existing_path.relative_to(repo_root).as_posix()
        previous_target = target_rel
        existing_entry = dict(index.entries[existing_path])
        is_modification = is_replacement(existing_entry, parsed)
        if is_modification and not reason_text(parsed.modification_reason):
            raise ValueError(
                f"Replacing a value in `{target_rel}` needs a reason: edit the "
                "issue and explain why in 'Reason for modification'."
            )
        validated, diff = _update_entry(existing_entry, parsed, target_rel)
        if not diff.strip():
            themerr_id = existing_entry.get("youtube_id_themerrdb")
            if parsed.youtube_id and parsed.youtube_id == themerr_id:
                raise NoChangesError(
                    f"No changes or additions detected for `{target_rel}`. "
                    "The submitted YouTube theme is already active via ThemerrDB, "
                    "and no other fields were modified."
                )
            raise NoChangesError(
                f"No changes or additions detected for `{target_rel}`. "
                "All submitted values match the existing entry."
            )
        media_comparison = format_media_comparison(existing_entry, validated)
        target_path = index.update(existing_path, validated)
        if target_path != existing_path:
            moved = target_path.relative_to(repo_root).as_posix()
            diff = diff.replace(f"+++ b/{target_rel}", f"+++ b/{moved}", 1)
            target_rel = moved
    else:
        target_path = entry_path(candidate, repo_root / "data")
        target_rel = target_path.relative_to(repo_root).as_posix()
        validated = validate_entry(candidate)
        is_modification = False
        media_comparison = format_media_comparison({}, validated)
        diff_lines = difflib.unified_diff(
            [],
            entry_json(validated).splitlines(keepends=True),
            fromfile="/dev/null",
            tofile=f"b/{target_rel}",
        )
        diff = "".join(diff_lines)

    if not dry_run:
        write_entry_json(target_path, validated)
        if existing_path is not None and existing_path != target_path:
            existing_path.unlink()

    return {
        "status": "ok",
        "entry": validated,
        "previous": existing_entry,
        "removed": False,
        "target": target_rel,
        "previous_target": previous_target,
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
        "youtube_id": validated.get("youtube_id_overturedb"),
    }
