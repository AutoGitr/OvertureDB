"""Allow dataset changes in pull requests opened by maintainers only."""

lazy import json
lazy import os
lazy from pathlib import Path
lazy from typing import Any

lazy from .github import BOT_LOGIN, api, git, load_state
lazy from .queue_prs import verify_pr
lazy from .queue_state import BRANCH

MAINTAINERS = {"OWNER", "MEMBER"}


def validate_changes(pr: dict[str, Any], changed: list[str]) -> None:
    if pr["author_association"] not in MAINTAINERS and any(
        path.startswith("data/") for path in changed
    ):
        if verified_queue_pr(pr):
            return
        raise ValueError(
            "Dataset changes come from contribution issues or maintainers."
        )


def verified_queue_pr(pr: dict[str, Any]) -> bool:
    """Username is only an early filter; protected queue state proves provenance."""
    if pr.get("user", {}).get("login") != BOT_LOGIN:
        return False
    repo = os.environ["GITHUB_REPOSITORY"]
    bot_id = api(f"users/{BOT_LOGIN}")["id"]
    state, _ = load_state(BRANCH)
    matches = [
        r
        for r in state.get("requests", [])
        if r["status"] == "checking"
        and r.get("attempt", {}).get("branch") == pr["head"]["ref"]
        and r["attempt"].get("head", pr["head"]["sha"]) == pr["head"]["sha"]
    ]
    if len(matches) != 1:
        return False
    live = api(f"repos/{repo}/pulls/{pr['number']}")
    attempt = {**matches[0]["attempt"], "head": pr["head"]["sha"]}
    verify_pr(repo, live, attempt, bot_id)
    return True


def main() -> None:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return
    event: dict[str, Any] = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text()
    )
    pr = event["pull_request"]
    diff = git(
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        f"{pr['base']['sha']}...{pr['head']['sha']}",
    )
    validate_changes(pr, diff.split("\0")[:-1])


if __name__ == "__main__":
    main()
