"""Check the least recently checked entries and report problems in one issue.

Checks artwork reachability, the 1% rule and theme availability, and warns about
artwork below the recommended resolution. Results are kept on the
``state/health`` branch.
"""

lazy import argparse
lazy import hashlib
lazy import os
lazy import sys
lazy from datetime import UTC, datetime
lazy from typing import Any, NamedTuple, TypedDict, cast
lazy from urllib.error import HTTPError
lazy from urllib.parse import urlencode

lazy from .catalog import (
    ROOT,
    TransientError,
    art_fields,
    aspect_problem,
    check_art_url,
    dataset,
    resolution_warning,
    theme_problem,
)
lazy from .github import BOT_LOGIN, api, load_state, pages, save_state

STATE_BRANCH = "state/health"
HEALTH_LIMIT = 200
HEALTH_LABEL = "health"
HEALTH_TITLE = "Dataset health"
HEALTH_MARKER = "<!-- overturedb-dataset-health -->"
MAX_ISSUE_BODY = 60000


class EntryState(TypedDict, closed=True):
    checked: str
    hash: str
    problems: list[str]
    warnings: list[str]


class State(TypedDict, closed=True):
    entries: dict[str, EntryState]


class Findings(NamedTuple):
    """What is broken in an entry, and what is only below the recommendation."""

    problems: list[str]
    warnings: list[str]


def empty_state() -> State:
    return {"entries": {}}


def select_entries(
    hashes: dict[str, str], known: dict[str, EntryState], limit: int
) -> list[str]:
    """Recheck changed entries with findings, plus *limit* from the rotation."""
    if limit < 0:
        raise ValueError("The health check limit must be zero or greater.")
    fixes = {
        path
        for path, entry in known.items()
        if path in hashes
        and (entry["problems"] or entry["warnings"])
        and entry["hash"] != hashes[path]
    }

    def priority(path: str) -> tuple[bool, str, str]:
        entry = known.get(path)
        if entry is None or entry["hash"] != hashes[path]:
            return False, "", path
        return True, entry["checked"], path

    return sorted(fixes) + sorted(hashes.keys() - fixes, key=priority)[:limit]


def artwork_findings(entry: dict[str, Any]) -> Findings:
    findings = Findings([], [])
    for kind, url in sorted(set(art_fields(entry))):
        try:
            size = check_art_url(url)
        except HTTPError as exc:
            exc.close()
            if exc.code == 429 or exc.code >= 500:
                raise TransientError(f"{url} answered HTTP {exc.code}") from exc
            findings.problems.append(f"{kind} {url}: HTTP {exc.code}")
            continue
        except OSError as exc:
            raise TransientError(str(exc)) from exc
        except ValueError as exc:
            findings.problems.append(f"{kind} {url}: {exc}")
            continue
        if size is None:
            continue
        if problem := aspect_problem(kind, *size):
            findings.problems.append(f"{kind} {url}: {problem}")
        elif warning := resolution_warning(kind, *size):
            findings.warnings.append(f"{kind} {url}: {warning}")
    return findings


def entry_findings(entry: dict[str, Any]) -> Findings:
    """Return what *entry* has wrong; TransientError means try again later."""
    findings = artwork_findings(entry)
    for field in ("youtube_id_overturedb", "youtube_id_themerrdb"):
        if (youtube_id := entry[field]) and (problem := theme_problem(youtube_id)):
            findings.problems.append(f"{field} {youtube_id}: {problem}")
    return findings


def check_health(
    state: State,
    files: dict[str, tuple[str, dict[str, Any]]],
    now: datetime,
    *,
    limit: int,
) -> State:
    """Check the selected entries and return the updated state."""
    known = {path: record for path, record in state["entries"].items() if path in files}
    for path in select_entries(
        {path: digest for path, (digest, _) in files.items()}, known, limit
    ):
        digest, entry = files[path]
        try:
            findings = entry_findings(entry)
        except TransientError as exc:
            print(f"Retrying {path} next run: {exc}", file=sys.stderr)
            continue
        known[path] = {
            "checked": now.date().isoformat(),
            "hash": digest,
            "problems": findings.problems,
            "warnings": findings.warnings,
        }
    return {"entries": known}


def describe(path: str, entries: dict[str, dict[str, Any]]) -> str:
    entry = entries[path]
    year = f" ({entry['year']})" if entry["year"] else ""
    return f"`{path}` {entry['title']}{year}"


def render(
    state: State, entries: dict[str, dict[str, Any]], *, limit: int = HEALTH_LIMIT
) -> str:
    checked = sum(1 for path in entries if path in state["entries"])
    lines = [
        HEALTH_MARKER,
        "Updated by the Dataset Health workflow. This run checks all changed "
        f"entries with reported findings, plus up to {limit} entries from the "
        "rotation (new and changed first, then least recently checked). "
        f"{checked:,} of {len(entries):,} entries have been checked so far.",
    ]
    records = sorted(state["entries"].items())
    sections = (
        ("Problems", [(path, record["problems"]) for path, record in records]),
        (
            "Below the recommended resolution",
            [(path, record["warnings"]) for path, record in records],
        ),
    )
    for heading, findings in sections:
        found = [(path, items) for path, items in findings if items]
        lines.extend(["", f"### {heading}", ""])
        for index, (path, items) in enumerate(found):
            item = [f"- {describe(path, entries)}", *(f"  - {i}" for i in items)]
            if sum(len(line) + 1 for line in [*lines, *item]) > MAX_ISSUE_BODY - 400:
                lines.append(f"- ... and {len(found) - index:,} more entries")
                break
            lines.extend(item)
        if not found:
            lines.append("None found.")
    return "\n".join(lines) + "\n"


def publish_report(repo: str, body: str) -> None:
    query = urlencode({"labels": HEALTH_LABEL, "state": "open", "per_page": 100})
    existing = next(
        (
            issue
            for issue in pages(f"repos/{repo}/issues?{query}")
            if issue["user"]["login"] == BOT_LOGIN
            and (issue["body"] or "").startswith(HEALTH_MARKER)
        ),
        None,
    )
    if existing and existing["body"] == body:
        return
    if existing:
        api(f"repos/{repo}/issues/{existing['number']}", {"body": body}, method="PATCH")
    else:
        api(
            f"repos/{repo}/issues",
            {"title": HEALTH_TITLE, "body": body, "labels": [HEALTH_LABEL]},
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=HEALTH_LIMIT,
        help="Rotating entries to check, in addition to changed problem entries",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the report")
    args = parser.parse_args()
    now = datetime.now(UTC)
    try:
        saved, parent = load_state(STATE_BRANCH)
        fields = set(EntryState.__annotations__)
        # A record that lacks a field is checked again instead of being read.
        initial: State = {
            "entries": {
                path: cast("EntryState", record)
                for path, record in saved.get("entries", {}).items()
                if set(record) == fields
            }
        }
        files = {
            path.relative_to(ROOT).as_posix(): (
                hashlib.sha1(path.read_bytes(), usedforsecurity=False).hexdigest(),
                entry,
            )
            for path, entry in dataset()
        }
        state = check_health(initial, files, now, limit=args.limit)
        report = render(
            state, {path: entry for path, (_, entry) in files.items()}, limit=args.limit
        )
        if args.dry_run:
            print(report)
            return 0
        publish_report(os.environ["GITHUB_REPOSITORY"], report)
        if state != initial:
            save_state(
                STATE_BRANCH,
                cast("dict[str, Any]", state),
                parent,
                f"Health check {now.date().isoformat()}",
            )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Dataset health check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
