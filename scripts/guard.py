"""Enforce dataset PR provenance and validate changed artwork."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from catalog import art_urls, check_art_url


def validate_changes(
    pr: dict[str, Any], repo: str, changed: list[str], deleted: list[str]
) -> list[str]:
    entries = [path for path in changed if path.startswith("data/")]
    if not entries:
        return []
    if any(path.startswith("data/") for path in deleted):
        raise ValueError(
            "Dataset deletion requires a separately reviewed maintenance change."
        )
    if (
        pr["head"]["repo"]["full_name"] != repo
        or pr["user"]["login"] != "overturedb[bot]"
        or not re.fullmatch(
            r"(?:contribution/(?:bulk-)?issue-[0-9]+|automation/themerrdb-[0-9-]+)",
            pr["head"]["ref"],
        )
    ):
        raise ValueError(
            "Dataset changes must be opened by overturedb[bot] "
            "from an internal contribution or import branch."
        )
    if len(entries) != len(changed) or any(
        not re.fullmatch(
            r"data/(movies|shows)/(tmdb-[0-9]+|tvdb-[0-9]+|imdb-tt[0-9]+)\.json", path
        )
        for path in entries
    ):
        raise ValueError("Dataset PRs may only change canonical dataset JSON files.")
    return entries


def main() -> None:
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return
    event: dict[str, Any] = json.loads(
        Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
    )
    pr = event["pull_request"]
    git = shutil.which("git")
    if git is None:
        raise OSError("git is required")
    diff = [
        git,
        "diff",
        "--name-only",
        "--no-renames",
        "-z",
        f"{pr['base']['sha']}...{pr['head']['sha']}",
    ]
    # Fixed git executable and GitHub commit SHAs passed as arguments, no shell.
    changed = subprocess.check_output(diff, text=True).rstrip("\0").split("\0")  # noqa: S603
    deleted = (
        subprocess.check_output([*diff, "--diff-filter=D"], text=True)  # noqa: S603
        .rstrip("\0")
        .split("\0")
    )
    entries = validate_changes(pr, os.environ["GITHUB_REPOSITORY"], changed, deleted)
    if pr["head"]["ref"].startswith("contribution/issue-"):
        values = [
            json.loads(Path(path).read_text(encoding="utf-8")) for path in entries
        ]
        for url in sorted(art_urls(values)):
            check_art_url(url)


if __name__ == "__main__":
    main()
