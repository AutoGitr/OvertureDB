"""Fail-closed provenance and checked merges for the single active dataset PR."""

lazy from typing import Any

lazy from . import github, queue_git, queue_issues
lazy from .changes import ConflictError, Entry, digest, file_changes, reconcile
lazy from .queue_state import Store


def verify_pr(
    repo: str, pr: dict[str, Any], attempt: dict[str, Any], bot_id: int
) -> None:
    if (
        pr["user"]["id"] != bot_id
        or pr["user"]["type"] != "Bot"
        or pr["head"]["repo"]["full_name"] != repo
        or pr["base"]["repo"]["full_name"] != repo
        or pr["base"]["ref"] != "main"
        or pr["head"]["ref"] != attempt["branch"]
        or pr["head"]["sha"] != attempt["head"]
        or pr.get("auto_merge") is not None
    ):
        raise ValueError("Unexpected PR ownership, head, base or native auto-merge")
    queue_git.verify_commit(repo, attempt["head"], attempt, bot_id)
    files = github.pages(f"repos/{repo}/pulls/{pr['number']}/files?per_page=100")
    paths = {f["filename"] for f in files}
    paths.update(f["previous_filename"] for f in files if f.get("status") == "renamed")
    if len(files) != pr["changed_files"] or paths != set(attempt["files"]):
        raise ValueError(
            "Complete PR diff does not match the generated dataset changes"
        )


def ensure_pr(
    repo: str, request: dict[str, Any], store: Store, bot_id: int
) -> dict[str, Any]:
    attempt = request["attempt"]
    attempt["head"] = queue_git.ensure_branch(repo, attempt, bot_id)
    store.save()
    prs = github.pages(
        f"repos/{repo}/pulls?state=all&head={repo.split('/')[0]}:{attempt['branch']}&per_page=100"
    )
    if len(prs) > 1:
        raise ValueError("Multiple PRs refer to the queued branch")
    if prs:
        number = prs[0]["number"]
    else:
        result = github.api(
            f"repos/{repo}/pulls",
            {
                "title": f"Apply dataset request {request['id'][:12]}",
                "body": attempt["audit"],
                "base": "main",
                "head": attempt["branch"],
                "maintainer_can_modify": False,
            },
        )
        number = result["number"]
    if attempt.get("pr") and attempt["pr"] != number:
        raise ValueError("Queued PR identity changed")
    attempt["pr"] = number
    store.save()
    return github.api(f"repos/{repo}/pulls/{number}")


def checks(repo: str, pr: dict[str, Any]) -> str:
    """GitHub remains authoritative for required contexts and ruleset enforcement."""
    sha = pr.get("merge_commit_sha") or pr["head"]["sha"]
    result = github.api(
        f"repos/{repo}/commits/{sha}/check-runs?per_page=100&filter=latest"
    )
    runs = result["check_runs"]
    if result["total_count"] > len(runs):
        raise ValueError("Too many check runs to verify safely")
    if any(
        r["conclusion"]
        in {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
        for r in runs
    ):
        return "failed"
    guard = any(
        r["name"] == "contribution-guard"
        and r["conclusion"] == "success"
        and r["app"]["slug"] == "github-actions"
        for r in runs
    )
    if not guard or any(r["status"] != "completed" for r in runs):
        return "pending"
    return "ready" if pr.get("mergeable_state") == "clean" else "pending"


def protections(repo: str, app_id: int) -> None:
    """Refuse publication until the cutover removed the app's main bypass."""
    rules = github.pages(f"repos/{repo}/rules/branches/main?per_page=100")
    required = {r["type"] for r in rules}
    if (
        not {"pull_request", "required_signatures", "required_status_checks"}
        <= required
    ):
        raise ValueError("Main must require PRs, signed commits and status checks")
    statuses = [r for r in rules if r["type"] == "required_status_checks"]
    if not any(
        r["parameters"].get("strict_required_status_checks_policy")
        and any(
            c["context"] == "contribution-guard"
            for c in r["parameters"]["required_status_checks"]
        )
        for r in statuses
    ):
        raise ValueError("Main must require the up-to-date contribution guard")
    for identity in {r["ruleset_id"] for r in rules}:
        rule = github.api(f"repos/{repo}/rulesets/{identity}")
        if any(
            a["actor_type"] == "Integration" and a["actor_id"] == app_id
            for a in rule.get("bypass_actors", [])
        ):
            raise ValueError("Remove the dataset app's main bypass before publication")


def finish(repo: str, request: dict[str, Any], store: Store, bot_id: int) -> None:
    if request["source"] == "import":
        return
    number = request["record"]["issue"]
    item = store.state["issues"][str(number)]
    item.update(status=request["status"], message=request.get("message", ""))
    store.save()
    queue_issues.status(repo, number, item, store, bot_id)
    if request["status"] in {"merged", "already satisfied"}:
        github.api(
            f"repos/{repo}/issues/{number}",
            {"state": "closed", "state_reason": "completed"},
            method="PATCH",
        )


def close_inactive(repo: str, store: Store) -> None:
    """Also repairs crashes between recording a stop and closing its PR."""
    for request in store.state["requests"]:
        attempt = request.get("attempt", {})
        if request["status"] in {"checking", "queued", "merged"} or not attempt:
            continue
        if not attempt.get("pr"):
            prs = github.pages(
                f"repos/{repo}/pulls?state=all&head="
                f"{repo.split('/')[0]}:{attempt['branch']}&per_page=100"
            )
            if not prs:
                continue
            if len(prs) != 1:
                raise ValueError("Ambiguous stopped request PRs")
            attempt["pr"] = prs[0]["number"]
            store.save()
        pr = github.api(f"repos/{repo}/pulls/{attempt['pr']}")
        if pr["state"] == "open":
            github.api(
                f"repos/{repo}/pulls/{attempt['pr']}",
                {
                    "state": "closed",
                    "body": attempt["audit"]
                    + "\n\nStopped: "
                    + request.get("message", request["status"]),
                },
                method="PATCH",
            )


def plan(request: dict[str, Any], entries: list[Entry]) -> dict[str, str | None]:
    record = request["record"]
    if request["source"] == "import":
        planned = queue_git.import_snapshot(entries, record["upstream"])
    else:
        if digest(record["changes"]) != record["digest"]:
            raise ValueError("Approved change digest is invalid")
        planned = reconcile(entries, record["changes"])
    return file_changes(entries, planned)


def new_attempt(
    request: dict[str, Any], base: str, files: dict[str, str | None]
) -> None:
    old = request.get("attempt", {})
    revision = request["record"].get("revision", request["record"].get("upstream"))
    request["attempt"] = {
        "branch": old.get(
            "branch", f"automation/dataset/{request['id'][:32]}-{request['generation']}"
        ),
        "base": base,
        "files": files,
        "previous_head": old.get("head"),
        "audit": f"Queue request: {request['id']}\nSource: {request['source']}\n"
        f"Source revision: {revision}\n"
        f"Generated changes: {digest(files)}",
    }
    if old.get("pr"):
        request["attempt"]["pr"] = old["pr"]
    request["status"] = "checking"


def retry(repo: str, request: dict[str, Any], store: Store) -> None:
    if request["status"] != "needs attention" or request.get("reapprove"):
        raise ValueError("Only parked requests with unchanged approval may be retried")
    close_inactive(repo, store)
    queue_issues.authorized(repo, request)
    store.state["sequence"] += 1
    request.update(
        status="queued",
        generation=request["generation"] + 1,
        sequence=store.state["sequence"],
    )
    request.pop("attempt", None)
    store.save()


def process(repo: str, request: dict[str, Any], store: Store, bot_id: int) -> None:
    attempt = request.get("attempt")
    if attempt and not attempt.get("head"):
        # Finish an interrupted refresh before planning against an even newer main.
        queue_issues.authorized(repo, request)
        ensure_pr(repo, request, store, bot_id)
    # Recover a confirmed merge before cancellation caused by our own issue closure.
    if attempt and attempt.get("pr") and attempt.get("head"):
        pr = github.api(f"repos/{repo}/pulls/{attempt['pr']}")
        verify_pr(repo, pr, attempt, bot_id)
        if pr["merged"]:
            request.update(status="merged", merge_sha=pr["merge_commit_sha"])
            store.save()
            finish(repo, request, store, bot_id)
            return
        if pr["state"] != "open":
            raise ValueError("The queued PR was closed without merging")
    queue_issues.authorized(repo, request)
    base, entries = queue_git.main_snapshot(repo)
    files = plan(request, entries)
    if not files:
        request["status"] = "already satisfied"
        store.save()
        close_inactive(repo, store)
        finish(repo, request, store, bot_id)
        return
    if not attempt or attempt["base"] != base:
        new_attempt(request, base, files)
        store.save()
    elif attempt["files"] != files:
        raise ValueError("Generated changes differ from queued PR provenance")
    pr = ensure_pr(repo, request, store, bot_id)
    attempt = request["attempt"]
    verify_pr(repo, pr, attempt, bot_id)
    if pr["merged"]:
        request.update(status="merged", merge_sha=pr["merge_commit_sha"])
        store.save()
    elif pr["state"] != "open":
        raise ValueError("Queued PR was closed")
    elif checks(repo, pr) == "failed":
        raise ValueError("Checks failed. Fix the cause and use @OvertureDB-bot retry.")
    elif checks(repo, pr) == "ready":
        merge(repo, request, store, bot_id)
    finish(repo, request, store, bot_id)


def merge(repo: str, request: dict[str, Any], store: Store, bot_id: int) -> None:
    attempt = request["attempt"]
    queue_issues.authorized(repo, request)
    base, entries = queue_git.main_snapshot(repo)
    if base != attempt["base"]:
        return  # A later invocation refreshes the PR and reruns CI.
    if plan(request, entries) != attempt["files"]:
        raise ConflictError("Approved effect changed before merge")
    pr = github.api(f"repos/{repo}/pulls/{attempt['pr']}")
    verify_pr(repo, pr, attempt, bot_id)
    if checks(repo, pr) != "ready":
        return
    # No native auto-merge: GitHub enforces rules, expected head and strict freshness.
    result = github.api(
        f"repos/{repo}/pulls/{attempt['pr']}/merge",
        {
            "sha": attempt["head"],
            "merge_method": "squash",
            "commit_title": f"Apply dataset request {request['id'][:12]}",
            "commit_message": attempt["audit"],
        },
        method="PUT",
    )
    if result.get("merged"):
        request.update(status="merged", merge_sha=result["sha"])
        store.save()


def tick(repo: str, store: Store, bot_id: int) -> None:
    close_inactive(repo, store)
    # Repair status/issue closing after a crash, without touching old completed issues.
    for request in store.state["requests"]:
        if request["status"] in {"merged", "already satisfied"} and not request.get(
            "notified"
        ):
            finish(repo, request, store, bot_id)
            request["notified"] = True
            store.save()
    request = store.next()
    if request is None:
        return
    try:
        process(repo, request, store, bot_id)
    except ValueError as exc:
        request.update(
            status="needs attention",
            message=str(exc),
            reapprove=isinstance(exc, ConflictError),
        )
        store.save()
        close_inactive(repo, store)
        finish(repo, request, store, bot_id)
        if isinstance(exc, ConflictError) and request["source"] != "import":
            store.state["issues"][str(request["record"]["issue"])]["refresh"] = True
            store.save()
