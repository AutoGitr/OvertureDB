"""Allow dataset changes in pull requests opened by maintainers only."""

lazy import json
lazy import os
lazy from pathlib import Path
lazy from typing import Any

lazy from .github import git

MAINTAINERS = {"OWNER", "MEMBER"}


def validate_changes(pr: dict[str, Any], changed: list[str]) -> None:
    if pr["author_association"] not in MAINTAINERS and any(
        path.startswith("data/") for path in changed
    ):
        raise ValueError(
            "Dataset changes come from contribution issues or maintainers."
        )


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
