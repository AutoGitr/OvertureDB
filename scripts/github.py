"""GitHub CLI access and the shared, reviewable dataset pull request flow."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run(executable: str, *args: str, stdin: str | None = None) -> str:
    resolved = shutil.which(executable)
    if resolved is None:
        raise OSError(f"{executable} is required")
    # Internal executables and argument arrays; input is never evaluated by a shell.
    result = subprocess.run(  # noqa: S603
        [resolved, *args],
        cwd=ROOT,
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{executable} command failed")
    return result.stdout.strip()


def gh(*args: str, payload: dict[str, Any] | None = None) -> str:
    if payload is None:
        return run("gh", *args)
    return run("gh", *args, "--input", "-", stdin=json.dumps(payload))


def api(path: str, payload: dict[str, Any] | None = None) -> Any:
    return json.loads(gh("api", path, payload=payload))


def pages(path: str) -> list[dict[str, Any]]:
    result: list[list[dict[str, Any]]] = json.loads(
        gh("api", path, "--paginate", "--slurp")
    )
    return [item for page in result for item in page]


def git(*args: str) -> str:
    return run("git", *args)


def create_pull_request(
    repo: str,
    *,
    branch: str,
    title: str,
    body: str,
    files: list[str],
    labels: list[str],
) -> str | None:
    """Publish changed files once, leaving all merges to the caller's policy."""
    if not files:
        raise ValueError("A pull request must specify its dataset files")
    existing = gh(
        "pr",
        "list",
        "--repo",
        repo,
        "--base",
        "main",
        "--head",
        branch,
        "--app",
        "overturedb",
        "--state",
        "all",
        "--json",
        "url",
        "--jq",
        ".[0].url // empty",
    )
    if existing:
        print(f"Changes already have a pull request: {existing}")
        return None
    if not git("status", "--porcelain", "--", *files):
        print("No dataset changes to publish.")
        return None

    gh("auth", "setup-git")
    git("switch", "-c", branch)
    git("config", "user.name", "overturedb[bot]")
    git("config", "user.email", "overturedb[bot]@users.noreply.github.com")
    git("add", "--", *files)
    git("commit", "--only", "-m", title, "--", *files)
    git("push", "origin", branch)
    with tempfile.TemporaryDirectory() as directory:
        body_file = Path(directory) / "body.md"
        body_file.write_text(body, encoding="utf-8")
        url = gh(
            "pr",
            "create",
            "--repo",
            repo,
            "--base",
            "main",
            "--head",
            branch,
            "--title",
            title,
            "--body-file",
            str(body_file),
            *(arg for label in labels for arg in ("--label", label)),
        )
    print(f"Created pull request: {url}")
    return url
