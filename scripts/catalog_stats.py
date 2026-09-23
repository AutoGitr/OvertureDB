"""Deterministic README statistics from the validated publication dataset."""

from dataclasses import asdict, dataclass
from html import escape
from typing import Any, TypedDict


@dataclass
class Counts:
    titles: int = 0
    posters: int = 0
    backgrounds: int = 0
    season_posters: int = 0
    shows_with_season_posters: int = 0
    themes: int = 0
    overturedb_themes: int = 0
    themerrdb_themes: int = 0
    titles_with_themes: int = 0
    core_complete: int = 0


def summarize(entries: list[dict[str, Any]]) -> dict[str, Counts]:
    """Count selections per entry; shared URLs/IDs still count for each title."""
    groups = {name: Counts() for name in ("movies", "shows", "total")}
    for entry in entries:
        poster = entry["poster_url"] is not None
        background = entry["background_url"] is not None
        overturedb = entry["youtube_id_overturedb"] is not None
        themerrdb = entry["youtube_id_themerrdb"] is not None
        seasons = len(entry.get("seasons", []))
        group = "movies" if entry["media_type"] == "movie" else "shows"
        for counts in (groups[group], groups["total"]):
            counts.titles += 1
            counts.posters += poster
            counts.backgrounds += background
            counts.season_posters += seasons
            counts.shows_with_season_posters += bool(seasons)
            counts.overturedb_themes += overturedb
            counts.themerrdb_themes += themerrdb
            counts.themes += overturedb + themerrdb
            counts.titles_with_themes += overturedb or themerrdb
            counts.core_complete += poster and background and (overturedb or themerrdb)
    return groups


class Statistics(TypedDict):
    source_revision: str
    generated_at: str
    counts: dict[str, dict[str, int]]


def statistics_json(
    groups: dict[str, Counts], *, revision: str, generated_at: str
) -> Statistics:
    return {
        "source_revision": revision,
        "generated_at": generated_at,
        "counts": {name: asdict(counts) for name, counts in groups.items()},
    }


def dashboard(
    groups: dict[str, Counts], *, revision: str, generated_at: str, dark: bool
) -> str:
    """Render a self-contained SVG, including accessible text and exact counts."""
    if dark:
        canvas, panel, ink, muted, border, accent = (
            "#17191e",
            "#202329",
            "#f2eee7",
            "#b1b3ba",
            "#373b44",
            "#d7b77e",
        )
    else:
        canvas, panel, ink, muted, border, accent = (
            "#faf9f6",
            "#ffffff",
            "#292b31",
            "#626a76",
            "#dfded8",
            "#806844",
        )
    total = groups["total"]
    metrics = (
        ("Movies", groups["movies"].titles, "catalog entries"),
        ("Shows", groups["shows"].titles, "catalog entries"),
        ("Posters", total.posters, "movie + show selections"),
        ("Backgrounds", total.backgrounds, "movie + show selections"),
        ("Season posters", total.season_posters, "includes season 0 / specials"),
        ("Themes", total.themes, "across both theme sources"),
    )
    description = "; ".join(f"{label}: {value:,}" for label, value, _ in metrics)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="790" '
        'viewBox="0 0 840 790" role="img" aria-labelledby="title description">',
        '<title id="title">OvertureDB catalog statistics</title>',
        f'<desc id="description">{escape(description)}. '
        "Coverage bars show titles with each selection, not unique files. "
        "Core complete means a poster, background and at least one theme.</desc>",
        f'<rect x="1" y="1" width="838" height="788" rx="20" '
        f'fill="{canvas}" stroke="{border}"/>',
        '<g font-family="Segoe UI, Helvetica, Arial, sans-serif">',
    ]

    def text(
        x: int,
        y: int,
        value: str,
        *,
        size: int = 14,
        color: str = ink,
        weight: int = 400,
        anchor: str = "start",
    ) -> None:
        parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>'
        )

    text(32, 78, "OvertureDB Stats", size=27, weight=600)
    text(
        32,
        106,
        f"{total.titles:,} titles · Community-curated artwork and theme music",
        color=muted,
    )
    for index, (label, value, note) in enumerate(metrics):
        x, y = 32 + (index % 3) * 264, 134 + (index // 3) * 116
        parts.append(
            f'<rect x="{x}" y="{y}" width="248" height="100" rx="12" '
            f'fill="{panel}" stroke="{border}"/>'
        )
        text(x + 18, y + 26, label, color=muted)
        text(x + 18, y + 63, f"{value:,}", size=32, weight=600)
        text(x + 18, y + 84, note, size=12, color=muted)

    text(32, 397, "COVERAGE", size=12, color=accent, weight=600)
    text(
        808,
        397,
        "Titles with a selection / catalog titles",
        size=12,
        color=muted,
        anchor="end",
    )
    for column, name in enumerate(("movies", "shows")):
        counts = groups[name]
        x = 32 + column * 400
        text(x, 428, name.title(), size=18, weight=600)
        rows = (
            ("Poster", counts.posters),
            ("Background", counts.backgrounds),
            ("Theme", counts.titles_with_themes),
            ("Core complete", counts.core_complete),
        )
        for row, (label, count) in enumerate(rows):
            y = 460 + row * 46
            ratio = count / counts.titles if counts.titles else 0
            percentage = f"{ratio:.1%}" if counts.titles else "n/a"
            text(x, y, label, size=13)
            text(
                x + 376,
                y,
                f"{count:,} / {counts.titles:,} · {percentage}",
                size=13,
                color=muted,
                anchor="end",
            )
            parts.append(
                f'<rect x="{x}" y="{y + 10}" width="376" '
                f'height="6" rx="3" fill="{border}"/>'
            )
            if count:
                parts.append(
                    f'<rect x="{x}" y="{y + 10}" width="{376 * ratio:.2f}" '
                    f'height="6" rx="3" fill="{accent}"/>'
                )

    parts.append(f'<path d="M32 638H808" stroke="{border}"/>')
    text(
        32,
        666,
        f"Theme selections: {total.overturedb_themes:,} OvertureDB · "
        f"{total.themerrdb_themes:,} ThemerrDB",
        size=13,
    )
    text(
        32,
        691,
        f"Season artwork: {groups['shows'].shows_with_season_posters:,} of "
        f"{groups['shows'].titles:,} shows have at least one season poster",
        size=13,
    )
    text(
        32,
        722,
        "Core complete = poster + background + theme; "
        "season completeness is not tracked.",
        size=12,
        color=muted,
    )
    text(
        32,
        758,
        f"Source snapshot {generated_at[:10]} · {revision[:7]}",
        size=12,
        color=muted,
    )
    text(
        808,
        758,
        "Refreshes with each catalog publication",
        size=12,
        color=muted,
        anchor="end",
    )
    parts.extend(("</g>", "</svg>\n"))
    return "\n".join(parts)
