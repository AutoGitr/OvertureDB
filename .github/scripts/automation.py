"""Issue contribution automation. Untrusted input is data, never shell code."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile

from catalog import (
    art_urls,
    check_art_url,
    public_https_destination,
)
from contribution import parse_issue_form, process_contribution
from import_bulk_export import import_bulk_export

if TYPE_CHECKING:
    from http.client import HTTPMessage

ROOT = Path(__file__).resolve().parents[2]
MARKER = "<!-- overturedb-contribution-preview -->"
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


def gh(*args: str, payload: dict[str, Any] | None = None) -> str:
    executable = shutil.which("gh")
    if executable is None:
        raise OSError("GitHub CLI is required")
    command = [executable, *args]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(  # noqa: S603
        command,
        input=json.dumps(payload) if payload is not None else None,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "GitHub CLI request failed")
    return result.stdout.strip()


def api(path: str, payload: dict[str, Any] | None = None) -> Any:
    return json.loads(gh("api", path, payload=payload))


def issue_labels(issue: dict[str, Any]) -> set[str]:
    return {label["name"] for label in issue["labels"]}


def contribution_kind(issue: dict[str, Any]) -> str:
    labels = issue_labels(issue)
    kinds = labels & {"movie", "show", "bulk"}
    if (
        issue["state"] != "open"
        or "pull_request" in issue
        or "contribution" not in labels
        or "rejected" in labels
        or len(kinds) != 1
    ):
        raise ValueError("Use one open movie, show or bulk contribution issue.")
    return kinds.pop()


def parse_command(body: str) -> tuple[str, str] | None:
    match = re.fullmatch(
        r"@OvertureDB-bot (approve|reject)(?:[ \t]+([^\r\n]+))?", body.strip()
    )
    if not match or (match[1] == "approve" and match[2]):
        return None
    return match[1], (match[2] or "").strip()


def approved_issue(event: dict[str, Any], repo: str) -> dict[str, Any]:
    comment = event["comment"]
    actor = comment["user"]["login"]
    permission = api(f"repos/{repo}/collaborators/{actor}/permission")["permission"]
    if permission not in {"admin", "maintain", "write"}:
        raise ValueError("Write access is required for contribution commands.")
    issue = api(f"repos/{repo}/issues/{event['issue']['number']}")
    contribution_kind(issue)
    if (
        issue["body"] != event["issue"]["body"]
        or issue["title"] != event["issue"]["title"]
        or issue_labels(issue) != issue_labels(event["issue"])
        or issue["updated_at"] > comment["created_at"]
    ):
        raise ValueError(
            "The issue changed after this command. Review it and approve again."
        )
    return issue


def gate(event: dict[str, Any], repo: str) -> None:
    command = parse_command(event["comment"]["body"])
    if command is None:
        return
    issue = approved_issue(event, repo)
    action, reason = command
    if action == "reject":
        path = f"repos/{repo}/issues/{issue['number']}"
        api(f"{path}/labels", {"labels": ["rejected"]})
        gh(
            "api",
            path,
            "--method",
            "PATCH",
            payload={"state": "closed", "state_reason": "not_planned"},
        )
        if reason:
            api(
                f"{path}/comments",
                {"body": "Contribution rejected.\n\n" + fenced(reason)},
            )
        return
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write("approved=true\n")


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


def prepare(issue: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    kind = contribution_kind(issue)
    number = issue["number"]
    if kind == "bulk":
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "selections.zip"
            download_archive(issue["body"] or "", archive)
            result = import_bulk_export(
                overture_dir=ROOT, archive_path=archive, dry_run=dry_run
            )
        if result["errors"]:
            raise ValueError("\n".join(result["errors"]))
        summary = (
            f"{result['created']} new, {result['backfilled']} backfilled, "
            f"{result['unchanged']} unchanged."
        )
        review = result["review_markdown"]
        if len(review) > 45000:
            review = "Review all selections in the attached archive and PR diff."
        return {
            "branch": f"contribution/bulk-issue-{number}",
            "title": f"Bulk contribution from #{number}",
            "body": summary + "\n\n" + review,
            "labels": ["contribution", "bulk"],
            "files": ["data"],
        }
    parsed = parse_issue_form(
        issue["body"] or "", issue["title"], sorted(issue_labels(issue))
    )
    result = process_contribution(parsed, ROOT, dry_run=dry_run)
    entry = result["entry"]
    for url in sorted(art_urls([entry])):
        check_art_url(url)
    labels = ["contribution", kind]
    if result["is_modification"]:
        labels.append("modification")
    action = "Update" if result["is_modification"] or result["is_addition"] else "Add"
    body = f"`{result['target']}`\n\n" + result["media_comparison"]
    if result["modification_reason"]:
        body += "\n\nReason:\n" + fenced(result["modification_reason"])
    diff = fenced(result["diff"], "diff")
    if len(body) + len(diff) <= 45000:
        body += (
            "\n\n<details><summary>Dataset diff</summary>\n\n" + diff + "\n</details>"
        )
    else:
        body = f"`{result['target']}`\n\nLarge contribution: review the full PR diff."
    return {
        "branch": f"contribution/issue-{number}",
        "title": f"{action} dataset entry from #{number}",
        "body": body,
        "labels": labels,
        "files": [result["target"]],
    }


def preview(event: dict[str, Any], repo: str) -> None:
    path = f"repos/{repo}/issues/{event['issue']['number']}"
    issue = api(path)
    # An old queued event must not resurrect a closed/rejected contribution.
    try:
        contribution_kind(issue)
    except ValueError:
        return
    try:
        result = prepare(issue, dry_run=True)
        body = result["body"]
        labels = issue_labels(issue)
        modification = "modification" in result["labels"]
        if modification and "modification" not in labels:
            api(f"{path}/labels", {"labels": ["modification"]})
        elif not modification and "modification" in labels:
            gh("api", f"{path}/labels/modification", "--method", "DELETE")
    except (ValueError, OSError, BadZipFile, RuntimeError) as exc:
        body = "Could not validate this contribution:\n\n" + fenced(str(exc))
    if len(body) > 50000:
        body = "Preview exceeds the comment limit. Review the attached archive."
    body = f"{MARKER}\n{body}\n\n" + (ROOT / ".github/bot_commands.md").read_text(
        encoding="utf-8"
    )
    current = api(path)
    if (
        current["body"] != issue["body"]
        or current["state"] != "open"
        or "rejected" in issue_labels(current)
    ):
        return
    pages = json.loads(gh("api", f"{path}/comments", "--paginate", "--slurp"))
    existing = next(
        (
            c
            for page in pages
            for c in page
            if c["user"]["login"] == "github-actions[bot]"
            and c["body"].startswith(MARKER)
        ),
        None,
    )
    if existing:
        gh(
            "api",
            f"repos/{repo}/issues/comments/{existing['id']}",
            "--method",
            "PATCH",
            payload={"body": body},
        )
    else:
        api(f"{path}/comments", {"body": body})


def enable_auto_merge(repo: str, pr_url: str) -> None:
    # gh --auto can merge immediately when branch protection is disabled.
    rules = api(f"repos/{repo}/rules/branches/main")
    required = [
        check
        for rule in rules
        if rule["type"] == "required_status_checks"
        for check in rule["parameters"]["required_status_checks"]
    ]
    if not any(
        c["context"] == "contribution-guard" and c.get("integration_id") == 15368
        for c in required
    ):
        print("PR requires manual merge: contribution-guard is not enforced on main.")  # noqa: T201
        return
    head = gh(
        "pr",
        "view",
        pr_url,
        "--repo",
        repo,
        "--json",
        "headRefOid",
        "--jq",
        ".headRefOid",
    )
    gh(
        "pr",
        "merge",
        pr_url,
        "--repo",
        repo,
        "--auto",
        "--squash",
        "--delete-branch",
        "--match-head-commit",
        head,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["gate", "preview", "prepare", "auto-merge"])
    parser.add_argument("--pr")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "auto-merge" and not args.pr:
        parser.error("auto-merge requires --pr")
    if args.command == "prepare" and args.output is None:
        parser.error("prepare requires --output")
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        if args.command == "auto-merge":
            enable_auto_merge(repo, args.pr)
            return 0
        event: dict[str, Any] = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        if args.command == "gate":
            gate(event, repo)
        elif args.command == "preview":
            preview(event, repo)
        else:
            issue = approved_issue(event, repo)
            result = prepare(issue, dry_run=False)
            result["body"] = f"Closes #{issue['number']}\n\n{result['body']}"
            args.output.write_text(json.dumps(result), encoding="utf-8")
    except (
        ValueError,
        OSError,
        BadZipFile,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"Automation failed: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
