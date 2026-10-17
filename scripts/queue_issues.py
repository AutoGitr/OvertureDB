"""Issue authorization, frozen previews and idempotent status comments."""

lazy import difflib
lazy import tempfile
lazy from pathlib import Path
lazy from typing import Any
lazy from zipfile import BadZipFile

lazy from . import automation, github, queue_prs
lazy from .catalog import entry_json, entry_path, write_entry_json
lazy from .changes import Change, Entry, between, change, digest
lazy from .contribution import (
    NoChangesError,
    format_media_comparison,
    parse_issue_form,
    process_contribution,
)
lazy from .import_bulk_export import import_bulk_export
lazy from .queue_state import TERMINAL, Store

MARKER = "<!-- overturedb-queue-status -->"
KINDS = {"movie", "show", "bulk"}


def revision(repo: str, issue: dict[str, Any]) -> str:
    owner, name = repo.split("/")
    result = github.api(
        "graphql",
        {
            "query": """
      query($owner:String!, $name:String!, $number:Int!) {
        repository(owner:$owner, name:$name) { issue(number:$number) { lastEditedAt } }
      }
    """,
            "variables": {"owner": owner, "name": name, "number": issue["number"]},
        },
    )
    if result.get("errors"):
        raise RuntimeError("Could not verify the issue edit history")
    events = github.pages(
        f"repos/{repo}/issues/{issue['number']}/timeline?per_page=100"
    )
    relevant = [
        e["id"]
        for e in events
        if e["event"] in {"renamed", "closed", "reopened"}
        or (e["event"] in {"labeled", "unlabeled"} and e["label"]["name"] in KINDS)
    ]
    return digest(
        {
            "title": issue["title"],
            "body": issue["body"],
            "kinds": sorted(automation.issue_labels(issue) & KINDS),
            "edited": result["data"]["repository"]["issue"]["lastEditedAt"],
            "events": relevant,
        }
    )


def freeze(issue: dict[str, Any], entries: list[Entry]) -> list[Change]:
    """Parse an attachment only here, before approval; never during publication."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "data").mkdir()
        for entry in entries:
            write_entry_json(entry_path(entry, root / "data"), entry)
        if automation.contribution_kind(issue) == "bulk":
            archive = root / "selections.zip"
            automation.download_archive(issue["body"] or "", archive)
            result = import_bulk_export(
                overture_dir=root, archive_path=archive, dry_run=True
            )
            if result["errors"]:
                raise ValueError(
                    "Bulk validation failed: " + "; ".join(result["errors"])
                )
            return between(result["original_entries"], result["planned_entries"])
        parsed = parse_issue_form(
            issue["body"] or "", issue["title"], sorted(automation.issue_labels(issue))
        )
        try:
            result = process_contribution(parsed, root, dry_run=True)
        except NoChangesError:
            return []
        if result["entry"]:
            automation.check_artwork(result["entry"], result["previous"])
        return [change(result["previous"], result["entry"])]


def render(operations: list[Change]) -> str:
    sections: list[str] = []
    for operation in operations:
        before, after = operation["before"], operation["after"]
        comparison = format_media_comparison(before or {}, after or {})
        diff = "".join(
            difflib.unified_diff(
                entry_json(before).splitlines(keepends=True) if before else [],
                entry_json(after).splitlines(keepends=True) if after else [],
                fromfile="reviewed",
                tofile="intended",
            )
        )
        sections.append(comparison + "\n\n" + automation.fenced(diff, "diff"))
    result = "\n\n".join(sections)
    if len(result) > 45000:
        return (
            f"This contribution changes {len(operations)} entries. "
            "Review the complete frozen record linked below before approving; "
            "it contains every original and intended value."
        )
    return result or "All submitted values already exist."


def status(
    repo: str, number: int, item: dict[str, Any], store: Store, bot_id: int
) -> None:
    path = f"repos/{repo}/issues/{number}"
    comments = github.pages(f"{path}/comments?per_page=100")
    existing = next(
        (
            c
            for c in comments
            if c["user"]["id"] == bot_id and c["body"].startswith(MARKER)
        ),
        None,
    )
    body = f"{MARKER}\n**{item['status']}**\n\n{item.get('message', '')}"
    if item.get("changes") is not None:
        body += "\n\n" + render(item["changes"])
        body += (
            f"\n\nChange digest: `{item['digest']}`. "
            f"[Complete frozen record](https://github.com/{repo}/blob/"
            f"{item['record_commit']}/state.json).\n\n"
            "Approve with `@OvertureDB-bot approve`; reject with "
            "`@OvertureDB-bot reject`. Retry parked checks with "
            "`@OvertureDB-bot retry`."
        )
    if existing and existing["body"] == body:
        if item["status"] == "awaiting approval" and not item.get("rendered_at"):
            item["rendered_at"] = existing["updated_at"]
            store.save()
        return
    response = github.api(
        f"repos/{repo}/issues/comments/{existing['id']}"
        if existing
        else f"{path}/comments",
        {"body": body},
        method="PATCH" if existing else "POST",
    )
    if item["status"] == "awaiting approval":
        item["rendered_at"] = response["updated_at"]
        store.save()


def can_write(repo: str, actor: str) -> bool:
    return github.api(f"repos/{repo}/collaborators/{actor}/permission")[
        "permission"
    ] in {
        "admin",
        "maintain",
        "write",
    }


def authorized(repo: str, request: dict[str, Any]) -> None:
    if request["source"] == "import":
        return
    record = request["record"]
    issue = github.api(f"repos/{repo}/issues/{record['issue']}")
    automation.contribution_kind(issue)
    if revision(repo, issue) != record["revision"]:
        raise ValueError("Contribution changed after approval")
    approval = github.api(f"repos/{repo}/issues/comments/{record['approval']['id']}")
    if (
        approval["user"]["id"] != record["approval"]["actor_id"]
        or approval["body"].strip() != "@OvertureDB-bot approve"
        or approval["updated_at"] != record["approval"]["created_at"]
        or not can_write(repo, approval["user"]["login"])
    ):
        raise ValueError(
            "Approval was edited, deleted, or its author lost write access"
        )
    comments = github.pages(
        f"repos/{repo}/issues/{record['issue']}/comments?per_page=100"
    )
    for comment in comments:
        command = automation.parse_command(comment["body"])
        if (
            comment["id"] > approval["id"]
            and command
            and command[0] == "reject"
            and can_write(repo, comment["user"]["login"])
        ):
            raise ValueError("Contribution was rejected")


def cancel(store: Store, number: int) -> None:
    for request in store.state["requests"]:
        if request["source"] == f"issue:{number}" and request["status"] not in TERMINAL:
            # Reconciler closes any active PR before starting a successor.
            request["status"] = "cancelled"
    store.save()


def preview(
    repo: str,
    issue: dict[str, Any],
    entries: list[Entry],
    store: Store,
    bot_id: int,
    current_revision: str,
) -> dict[str, Any]:
    number = issue["number"]
    cancel(store, number)
    comments = github.pages(f"repos/{repo}/issues/{number}/comments?per_page=100")
    item: dict[str, Any] = {
        "revision": current_revision,
        "status": "awaiting approval",
        "cursor": max((c["id"] for c in comments), default=0),
    }
    try:
        operations = freeze(issue, entries)
        item.update(changes=operations, digest=digest(operations))
    except (ValueError, OSError, BadZipFile) as exc:
        item.update(status="needs attention", message=str(exc)[:5000])
    store.state["issues"][str(number)] = item
    store.save()
    item["record_commit"] = store.parent
    store.save()
    status(repo, number, item, store, bot_id)
    return item


def commands(repo: str, number: int, item: dict[str, Any], store: Store) -> None:
    comments = github.pages(f"repos/{repo}/issues/{number}/comments?per_page=100")
    for comment in sorted(comments, key=lambda c: c["id"]):
        if comment["id"] <= item["cursor"]:
            continue
        body = comment["body"].strip()
        command = automation.parse_command(body)
        if body == "@OvertureDB-bot retry":
            command = ("retry", "")
        if command and can_write(repo, comment["user"]["login"]):
            handle_command(repo, number, item, store, comment, command[0])
        item["cursor"] = comment["id"]
        store.save()


def handle_command(
    repo: str,
    number: int,
    item: dict[str, Any],
    store: Store,
    comment: dict[str, Any],
    action: str,
) -> None:
    if action == "reject":
        cancel(store, number)
        item["status"] = "cancelled"
        store.save()
        github.api(
            f"repos/{repo}/issues/{number}",
            {"state": "closed", "state_reason": "not_planned"},
            method="PATCH",
        )
    elif action == "retry":
        request = next(
            (
                r
                for r in reversed(store.state["requests"])
                if r["source"] == f"issue:{number}"
            ),
            None,
        )
        if (
            request
            and request["status"] == "needs attention"
            and not request.get("reapprove")
        ):
            queue_prs.retry(repo, request, store)
            item["status"] = "queued"
            store.save()
    elif (
        item["status"] == "awaiting approval"
        and item.get("rendered_at")
        and comment["created_at"] > item["rendered_at"]
        and comment["updated_at"] == comment["created_at"]
    ):
        record = {
            "issue": number,
            "revision": item["revision"],
            "changes": item["changes"],
            "digest": item["digest"],
            "approval": {
                "id": comment["id"],
                "actor": comment["user"]["login"],
                "actor_id": comment["user"]["id"],
                "created_at": comment["created_at"],
            },
        }
        store.enqueue(f"issue:{number}", record)
        item["status"] = "queued"
        store.save()


def sync(repo: str, entries: list[Entry], store: Store, bot_id: int) -> None:
    issues = github.pages(f"repos/{repo}/issues?state=open&per_page=100")
    open_numbers = {str(i["number"]) for i in issues}
    for number, item in store.state["issues"].items():
        if number not in open_numbers and item["status"] not in TERMINAL:
            cancel(store, int(number))
            item["status"] = "cancelled"
            store.save()
            status(repo, int(number), item, store, bot_id)
    for issue in issues:
        number = issue["number"]
        try:
            automation.contribution_kind(issue)
        except ValueError:
            if str(number) in store.state["issues"]:
                cancel(store, number)
                item = store.state["issues"][str(number)]
                item.update(
                    status="needs attention",
                    message="Use exactly one contribution-kind label.",
                )
                store.save()
                status(repo, number, item, store, bot_id)
            continue
        current = revision(repo, issue)
        item = store.state["issues"].get(str(number))
        if item is None or item["revision"] != current or item.get("refresh"):
            item = preview(repo, issue, entries, store, bot_id, current)
        commands(repo, number, item, store)
        status(repo, number, item, store, bot_id)
