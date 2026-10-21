"""Issue contribution automation. Untrusted input is data, never shell code."""

lazy import hashlib
lazy import json
lazy import os
lazy import re
lazy import tempfile
lazy import time
lazy from dataclasses import dataclass
lazy from http.client import HTTPMessage
lazy from pathlib import Path
lazy from typing import IO, Any
lazy from urllib.request import HTTPRedirectHandler, Request, build_opener
lazy from zipfile import BadZipFile

lazy from schema.contract import IDENTITY_FIELDS

lazy from . import github, publication
lazy from .catalog import (
    ROOT,
    art_fields,
    art_urls,
    aspect_problem,
    check_art_url,
    entry_json,
    public_https_destination,
)
lazy from .contribution import (
    NoChangesError,
    parse_issue_form,
    process_contribution,
)
lazy from .import_bulk_export import import_bulk_export

KINDS = frozenset({"movie", "show", "bulk"})
MARKER = "<!-- overturedb-preview -->"
FINGERPRINT_RE = re.compile(r"<!-- fingerprint: ([0-9a-f]{64}) -->")
ATTACHMENT = re.compile(
    r"https://github\.com/(?:user-attachments/(?:assets/[\w-]+|files/\d+/[\w.~%-]+)"
    r"|[\w.-]+/[\w.-]+/files/\d+/[\w.~%-]+)(?=$|[\s)<>])"
)
ATTACHMENT_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "user-images.githubusercontent.com",
    "github-production-user-asset-6210df.s3.amazonaws.com",
}
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024


@dataclass(slots=True, frozen=True)
class Plan:
    kind: str
    headline: str
    commit_body: str
    preview_body: str
    fingerprint: str
    additions: dict[str, str]
    deletions: list[str]
    is_modification: bool = False


def issue_labels(issue: dict[str, Any]) -> set[str]:
    return {label["name"] for label in issue["labels"]}


def contribution_kind(issue: dict[str, Any]) -> str:
    labels = issue_labels(issue)
    kinds = labels & KINDS
    if issue["state"] != "open" or "pull_request" in issue or len(kinds) != 1:
        raise ValueError("Use one open movie, show or bulk contribution issue.")
    return next(iter(kinds))


def parse_command(body: str) -> tuple[str, str] | None:
    match = re.fullmatch(
        r"@OvertureDB-bot (approve|reject)(?:[ \t]+([^\r\n]+))?", body.strip()
    )
    if not match or (match[1] == "approve" and match[2]):
        return None
    return match[1], (match[2] or "").strip()


def can_write(repo: str, actor: str) -> bool:
    return github.api(f"repos/{repo}/collaborators/{actor}/permission")[
        "permission"
    ] in {
        "admin",
        "maintain",
        "write",
    }


class AttachmentRedirectHandler(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        public_https_destination(newurl, allowed_hosts=ATTACHMENT_HOSTS)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_archive(body: str, target: Path) -> None:
    urls = set(ATTACHMENT.findall(body))
    if len(urls) != 1:
        raise ValueError("Attach exactly one GitHub-hosted selections ZIP.")
    url = urls.pop()
    public_https_destination(url, allowed_hosts={"github.com"})
    # HTTPS and host validated above; redirects undergo the same validation.
    request = Request(url, headers={"User-Agent": "OvertureDB"})  # noqa: S310
    opener = build_opener(AttachmentRedirectHandler())
    deadline = time.monotonic() + 60
    total = 0
    with opener.open(request, timeout=20) as response, target.open("wb") as output:
        while chunk := response.read(65536):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES or time.monotonic() > deadline:
                raise ValueError(
                    "Attachment exceeds the 10 MB or 60 second download limit."
                )
            output.write(chunk)


def fenced(value: str, language: str = "text") -> str:
    fence = "`" * max(
        3, max((len(m[0]) + 1 for m in re.finditer(r"`+", value)), default=3)
    )
    return f"{fence}{language}\n{value}\n{fence}"


def check_artwork(entry: dict[str, Any], previous: dict[str, Any] | None) -> None:
    """Check that all artwork is reachable and new artwork follows the 1% rule."""
    existing: set[str] = art_urls([previous]) if previous else set()
    for art_kind, url in sorted(set(art_fields(entry))):
        size = check_art_url(url)
        if url in existing or size is None:
            continue
        if problem := aspect_problem(art_kind, *size):
            raise ValueError(
                f"The {art_kind} {url} is {problem}. "
                "See the 1% rule in the selection guidelines in CONTRIBUTING.md."
            )


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _flat_fields(entry: dict[str, Any] | None) -> dict[str, Any]:
    if not entry:
        return {}
    flat = {key: value for key, value in entry.items() if key != "seasons"}
    for season in entry.get("seasons", []):
        flat[f"seasons/{season['season_num']}"] = season
    return flat


def _entry_changes(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> dict[str, Any]:
    if before is None:
        return {"created": after}
    if after is None:
        return {"removed": before}
    old, new = _flat_fields(before), _flat_fields(after)
    return {
        "identities": {field: before.get(field) for field in IDENTITY_FIELDS},
        "fields": {
            key: [old.get(key), new.get(key)]
            for key in sorted(old.keys() | new.keys())
            if old.get(key) != new.get(key)
        },
    }


def _evaluate_single(issue: dict[str, Any], root: Path) -> Plan:
    parsed = parse_issue_form(
        issue["body"] or "", issue["title"], sorted(issue_labels(issue))
    )
    result = process_contribution(parsed, root, dry_run=True)
    if result["entry"]:
        check_artwork(result["entry"], result["previous"])
    target: str = result["target"]
    previous_target: str | None = result.get("previous_target")
    if result["removed"]:
        additions: dict[str, str] = {}
        deletions = [target]
        action = "Remove"
        subject = result["previous"]
    else:
        additions = {target: entry_json(result["entry"])}
        deletions = (
            [previous_target] if previous_target and previous_target != target else []
        )
        action = "Update" if result["previous"] is not None else "Add"
        subject = result["entry"]
    year = f" ({subject['year']})" if subject.get("year") else ""
    headline = (
        f"{action} {parsed.media_type}: {subject['title']}{year} (#{issue['number']})"
    )
    sections: list[str] = []
    if reason := result.get("modification_reason"):
        sections.append(f"**Reason:** {reason}")
    if comparison := result.get("media_comparison"):
        sections.append(comparison)
    sections.append(fenced(result["diff"].rstrip("\n"), "diff"))
    fingerprint = _digest(
        {
            "kind": parsed.media_type,
            "title": issue["title"],
            "body": issue["body"] or "",
            "changes": _entry_changes(result["previous"], result["entry"]),
        }
    )
    return Plan(
        kind=parsed.media_type,
        headline=headline,
        commit_body=f"Closes #{issue['number']}",
        preview_body="\n\n".join(sections),
        fingerprint=fingerprint,
        additions=additions,
        deletions=deletions,
        is_modification=bool(result.get("is_modification")),
    )


def _format_conflict_message(message: str) -> str:
    match = re.match(r"^Conflicting (\w+): existing=([^,]+), incoming=(.+)$", message)
    if match:
        field, existing, incoming = match.groups()
        return f"Conflicting `{field}`: existing=`{existing}`, incoming=`{incoming}`"
    return message


def format_bulk_errors(errors: list[str]) -> str:
    count = len(errors)
    s = "s" if count != 1 else ""
    lines = [
        f"Bulk validation failed with {count} error{s}:",
        "",
    ]
    for err in errors[:50]:
        if ": " in err:
            name, _, message = err.partition(": ")
            lines.append(f"- `{name}`: {_format_conflict_message(message)}")
        else:
            lines.append(f"- {err}")
    if count > 50:
        lines.append(f"\n- ... and {count - 50} more errors")
    lines.append(
        "\nPlease fix or remove these entries from your export archive "
        "and update the issue attachment."
    )
    return "\n".join(lines)


def _format_error(message: str, *, max_chars: int = 5000) -> str:
    text = message.strip()
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        truncated = truncated[:last_nl]
    return f"{truncated}\n\n... (error message truncated)"


def format_bulk_summary(result: dict[str, Any]) -> str:
    created = result["created"]
    backfilled = result["backfilled"]
    unchanged = result["unchanged"]
    total = result.get("total_incoming", created + backfilled + unchanged)

    created_kinds = result.get("created_kinds", {})
    backfilled_kinds = result.get("backfilled_kinds", {})

    created_details = ", ".join(
        f"{created_kinds[k]:,} {k}"
        for k in ("posters", "backgrounds", "season posters", "themes")
        if created_kinds.get(k)
    )
    if not created_details:
        created_details = "Full records created" if created > 0 else "-"

    backfilled_details = ", ".join(
        f"{backfilled_kinds[k]:,} {k}"
        for k in (
            "identifiers",
            "release years",
            "posters",
            "backgrounds",
            "season posters",
            "themes",
        )
        if backfilled_kinds.get(k)
    )
    if not backfilled_details:
        backfilled_details = "-"

    unchanged_details = "Identical to database" if unchanged > 0 else "-"

    lines = [
        "| Status | Count | Details |",
        "| :--- | :--- | :--- |",
        f"| **New entries** | {created:,} | {created_details} |",
        f"| **Updated entries** | {backfilled:,} | {backfilled_details} |",
        f"| **Unchanged** | {unchanged:,} | {unchanged_details} |",
        f"| **Total in export** | {total:,} | |",
    ]
    return "\n".join(lines)


def _evaluate_bulk(issue: dict[str, Any], root: Path) -> Plan:
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "selections.zip"
        download_archive(issue["body"] or "", archive)
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        result = import_bulk_export(
            overture_dir=root, archive_path=archive, dry_run=True
        )
    if result["errors"]:
        raise ValueError(format_bulk_errors(result["errors"]))
    created, backfilled = result["created"], result["backfilled"]
    if created == 0 and backfilled == 0:
        raise NoChangesError("All submitted values already exist.")
    headline = (
        f"Bulk contribution: {created} added, {backfilled} updated (#{issue['number']})"
    )
    summary = format_bulk_summary(result)
    preview_body = f"{summary}\n\n{result['review_markdown']}".strip()
    fingerprint = _digest(
        {
            "kind": "bulk",
            "title": issue["title"],
            "body": issue["body"] or "",
            "archive": archive_hash,
            "additions": result["additions"],
            "deletions": result["deletions"],
        }
    )
    return Plan(
        kind="bulk",
        headline=headline,
        commit_body=f"Closes #{issue['number']}",
        preview_body=preview_body,
        fingerprint=fingerprint,
        additions=result["additions"],
        deletions=result["deletions"],
    )


def evaluate_issue(issue: dict[str, Any], root: Path) -> Plan:
    if contribution_kind(issue) == "bulk":
        plan = _evaluate_bulk(issue, root)
    else:
        plan = _evaluate_single(issue, root)
    if len(plan.preview_body.encode("utf-8")) > 55_000:
        raise ValueError(
            "The complete preview is too large for one comment. "
            "Split the contribution into smaller issues or archives."
        )
    return plan


def find_preview_comment(repo: str, number: int) -> dict[str, Any] | None:
    comments = github.pages(f"repos/{repo}/issues/{number}/comments?per_page=100")
    return next(
        (
            c
            for c in comments
            if c.get("user", {}).get("login") == github.BOT_LOGIN
            and (c.get("body") or "").startswith(MARKER)
        ),
        None,
    )


def upsert_comment(repo: str, number: int, body: str) -> dict[str, Any]:
    existing = find_preview_comment(repo, number)
    if existing and existing["body"] == body:
        return existing
    return github.api(
        f"repos/{repo}/issues/comments/{existing['id']}"
        if existing
        else f"repos/{repo}/issues/{number}/comments",
        {"body": body},
        method="PATCH" if existing else "POST",
    )


def sync_edit_label(repo: str, issue: dict[str, Any], *, is_modification: bool) -> None:
    labels = issue_labels(issue)
    number = issue["number"]
    if is_modification and "edit" not in labels:
        github.api(f"repos/{repo}/issues/{number}/labels", {"labels": ["edit"]})
    elif not is_modification and "edit" in labels:
        github.api(f"repos/{repo}/issues/{number}/labels/edit", method="DELETE")


def _commands_footer() -> str:
    return (ROOT / ".github" / "bot_commands.md").read_text(encoding="utf-8").strip()


def preview_issue(
    repo: str, issue: dict[str, Any], root: Path, *, notice: str = ""
) -> None:
    number = issue["number"]
    try:
        plan = evaluate_issue(issue, root)
    except NoChangesError as exc:
        sync_edit_label(repo, issue, is_modification=False)
        upsert_comment(repo, number, f"{MARKER}\n**Already satisfied**\n\n{exc}")
        return
    except (ValueError, OSError, BadZipFile) as exc:
        upsert_comment(
            repo, number, f"{MARKER}\n**Needs attention**\n\n{_format_error(str(exc))}"
        )
        return

    post_preview(repo, issue, plan, notice=notice)


def post_preview(
    repo: str, issue: dict[str, Any], plan: Plan, *, notice: str = ""
) -> None:
    sync_edit_label(repo, issue, is_modification=plan.is_modification)
    parts = [f"{MARKER}\n<!-- fingerprint: {plan.fingerprint} -->"]
    if notice:
        parts.append(notice)
    parts.append(plan.preview_body)
    parts.append(_commands_footer())
    upsert_comment(repo, issue["number"], "\n\n".join(parts))


def approved_plan(
    repo: str, issue: dict[str, Any], comment: dict[str, Any], root: Path
) -> Plan | None:
    number = issue["number"]
    existing = find_preview_comment(repo, number)
    match = FINGERPRINT_RE.search(existing["body"]) if existing else None
    recorded_fp = match[1] if match else None
    try:
        plan = evaluate_issue(issue, root)
    except NoChangesError as exc:
        if not approval_is_current(repo, issue, comment):
            return
        upsert_comment(repo, number, f"{MARKER}\n**Already satisfied**\n\n{exc}")
        github.api(
            f"repos/{repo}/issues/{number}",
            {"state": "closed", "state_reason": "completed"},
            method="PATCH",
        )
        return None
    except (ValueError, OSError, BadZipFile) as exc:
        upsert_comment(
            repo, number, f"{MARKER}\n**Needs attention**\n\n{_format_error(str(exc))}"
        )
        return None

    if (
        existing is None
        or existing["updated_at"] >= comment["created_at"]
        or recorded_fp != plan.fingerprint
    ):
        post_preview(
            repo,
            issue,
            plan,
            notice=(
                "> [!NOTE]\n"
                "> The issue or target entry changed since the previous preview. "
                "Review the updated preview below and comment "
                "`@OvertureDB-bot approve` again."
            ),
        )
        return None

    if not approval_is_current(repo, issue, comment):
        return None
    return plan


def approve_issue(
    repo: str, issue: dict[str, Any], comment: dict[str, Any], root: Path
) -> None:
    plan: Plan | None = None

    def prepare(candidate: Path) -> publication.Commit | None:
        nonlocal plan
        plan = approved_plan(repo, issue, comment, candidate)
        if plan is None:
            return None
        return plan.headline, plan.commit_body, plan.additions, plan.deletions

    number = issue["number"]
    try:
        commit_sha = publication.publish(
            repo, root, prepare, lambda: approval_is_current(repo, issue, comment)
        )
    except RuntimeError, OSError:
        upsert_comment(
            repo,
            number,
            f"{MARKER}\n**Checks or commit need attention**\n\n"
            "Validation or publication did not complete. "
            "Check the workflow log and `main` "
            "before retrying. If `main` moved, comment `@OvertureDB-bot approve` "
            "again to refresh the preview against the latest dataset.",
        )
        raise
    if commit_sha is None or plan is None:
        return
    commit_ref = f"[`{commit_sha[:7]}`](https://github.com/{repo}/commit/{commit_sha})"
    upsert_comment(
        repo,
        number,
        f"{MARKER}\n**Merged** in {commit_ref}\n\n{plan.preview_body}",
    )
    github.api(
        f"repos/{repo}/issues/{number}",
        {"state": "closed", "state_reason": "completed"},
        method="PATCH",
    )


def reject_issue(repo: str, issue: dict[str, Any], reason: str) -> None:
    number = issue["number"]
    body = f"{MARKER}\n**Rejected**" + (f"\n\n**Reason:** {reason}" if reason else "")
    upsert_comment(repo, number, body)
    github.api(
        f"repos/{repo}/issues/{number}",
        {"state": "closed", "state_reason": "not_planned"},
        method="PATCH",
    )


def approval_is_current(
    repo: str, issue: dict[str, Any], comment: dict[str, Any]
) -> bool:
    """Recheck editable approval and issue data after potentially slow validation."""
    live = github.api(f"repos/{repo}/issues/{issue['number']}")
    if (
        live["state"] != "open"
        or any(live.get(key) != issue.get(key) for key in ("title", "body"))
        or issue_labels(live) & KINDS != issue_labels(issue) & KINDS
    ):
        return False
    current = github.api(f"repos/{repo}/issues/comments/{comment['id']}")
    return (
        current.get("body") == comment.get("body")
        and current.get("updated_at") == comment.get("updated_at")
        and current["user"]["login"] == comment["user"]["login"]
        and can_write(repo, current["user"]["login"])
    )


def main() -> None:
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Contribution automation must run on main")
    repo = os.environ["GITHUB_REPOSITORY"]
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event: dict[str, Any] = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    if event_name == "workflow_dispatch":
        raw_issue = os.environ.get("INPUT_ISSUE", "").strip()
        if not raw_issue:
            return
        issue = github.api(f"repos/{repo}/issues/{int(raw_issue)}")
        if issue["state"] == "open" and "pull_request" not in issue:
            preview_issue(repo, issue, ROOT)
        return

    number = int(event["issue"]["number"])
    issue = github.api(f"repos/{repo}/issues/{number}")
    if issue["state"] != "open" or "pull_request" in issue:
        return
    if not (issue_labels(issue) & KINDS):
        return

    if event_name == "issues":
        preview_issue(repo, issue, ROOT)
    elif event_name == "issue_comment":
        comment = event["comment"]
        command = parse_command(comment.get("body") or "")
        if not command or not can_write(repo, comment["user"]["login"]):
            return
        action, reason = command
        if action == "reject":
            reject_issue(repo, issue, reason)
        else:
            approve_issue(repo, issue, comment, ROOT)


if __name__ == "__main__":
    main()
