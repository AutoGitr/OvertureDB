"""Read catalog snapshots and create GitHub-signed, data-only bot commits."""

lazy import base64
lazy import json
lazy import re
lazy import tempfile
lazy from pathlib import Path
lazy from typing import Any
lazy from zipfile import ZipFile

lazy from schema.contract import validate_entries

lazy from . import github
lazy from .catalog import dataset, validate_entry_path, write_entry_json
lazy from .changes import Entry, file_changes
lazy from .import_themerrdb import import_themerrdb


def snapshot(sha: str) -> list[Entry]:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected a pinned Git commit")
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "data.zip"
        github.git("archive", "--format=zip", f"--output={archive}", sha, "data")
        with ZipFile(archive) as files:
            entries: list[Entry] = []
            for name in files.namelist():
                if name.endswith("/"):
                    continue
                entry: Entry = json.loads(files.read(name))
                validate_entry_path(Path(directory) / name, entry, Path(directory))
                entries.append(entry)
    return validate_entries(list(entries))


def main_snapshot(repo: str) -> tuple[str, list[Entry]]:
    sha = github.api(f"repos/{repo}/git/ref/heads/main")["object"]["sha"]
    github.git("fetch", "--depth=1", "origin", sha)
    return sha, snapshot(sha)


def import_snapshot(entries: list[Entry], revision: str) -> list[Entry]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Import requires an immutable upstream commit")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "data").mkdir()
        for entry in entries:
            from_path = file_changes([], [entry])
            path = next(iter(from_path))
            write_entry_json(root / path, entry)
        upstream = root / "upstream"
        github.git("init", "-q", str(upstream))
        github.git(
            "-C",
            str(upstream),
            "fetch",
            "--depth=1",
            "https://github.com/LizardByte/ThemerrDB.git",
            revision,
        )
        github.git("-C", str(upstream), "checkout", "--detach", "FETCH_HEAD")
        stats, _ = import_themerrdb(upstream, root)
        if stats["skipped_error"] or stats["skipped_invalid"]:
            raise ValueError("Pinned ThemerrDB import contains validation errors")
        return [entry for _, entry in dataset(root)]


def signed_commit(repo: str, attempt: dict[str, Any], title: str) -> str:
    files = attempt["files"]
    additions = [
        {"path": path, "contents": base64.b64encode(content.encode()).decode()}
        for path, content in files.items()
        if content is not None
    ]
    deletions = [{"path": path} for path, content in files.items() if content is None]
    result = github.api(
        "graphql",
        {
            "query": """
        mutation($input: CreateCommitOnBranchInput!) {
          createCommitOnBranch(input: $input) { commit { oid } }
        }
        """,
            "variables": {
                "input": {
                    "branch": {
                        "repositoryNameWithOwner": repo,
                        "branchName": attempt["branch"],
                    },
                    "expectedHeadOid": attempt["base"],
                    "message": {"headline": title, "body": attempt["audit"]},
                    "fileChanges": {"additions": additions, "deletions": deletions},
                }
            },
        },
    )
    if result.get("errors"):
        raise RuntimeError("GitHub rejected the signed commit mutation")
    return result["data"]["createCommitOnBranch"]["commit"]["oid"]


def verify_commit(repo: str, head: str, attempt: dict[str, Any], bot_id: int) -> None:
    commit = github.api(f"repos/{repo}/commits/{head}")
    if (
        commit.get("author", {}).get("id") != bot_id
        or not commit["commit"]["verification"]["verified"]
        or [p["sha"] for p in commit["parents"]] != [attempt["base"]]
        or commit["commit"]["message"].split("\n\n", 1)[-1] != attempt["audit"]
    ):
        raise ValueError(
            "Unexpected bot commit identity, signature, parent or audit record"
        )
    github.git("fetch", "--depth=2", "origin", head)
    raw = github.git("diff", "--no-renames", "--name-only", attempt["base"], head)
    if set(raw.splitlines()) != set(attempt["files"]):
        raise ValueError("PR contains unexpected files")
    for path, content in attempt["files"].items():
        if not re.fullmatch(r"data/(movies|shows)/[\w-]+\.json", path):
            raise ValueError("PR contains non-dataset files")
        if content is not None:
            mode = github.git("ls-tree", head, "--", path).split()[0]
            actual = github.git("rev-parse", f"{head}:{path}")
            with tempfile.TemporaryDirectory() as directory:
                expected = Path(directory) / "entry.json"
                expected.write_bytes(content.encode("utf-8"))
                expected_blob = github.git("hash-object", str(expected))
            if mode != "100644" or actual != expected_blob:
                raise ValueError("PR content differs from generated changes")
        elif github.git("ls-tree", head, "--", path):
            raise ValueError("Expected entry deletion is missing")


def ensure_branch(repo: str, attempt: dict[str, Any], bot_id: int) -> str:
    branch, base = attempt["branch"], attempt["base"]
    refs = github.pages(f"repos/{repo}/git/matching-refs/heads/{branch}")
    exact = [r for r in refs if r["ref"] == f"refs/heads/{branch}"]
    if not exact:
        github.api(
            f"repos/{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": base}
        )
        head = base
    else:
        head = exact[0]["object"]["sha"]
    previous = attempt.get("previous_head")
    if previous and head == previous:
        github.gh("auth", "setup-git")
        github.git(
            "push",
            f"--force-with-lease=refs/heads/{branch}:{previous}",
            "origin",
            f"{base}:refs/heads/{branch}",
        )
        head = base
    if head == base:
        head = signed_commit(repo, attempt, "Apply queued dataset changes")
    if attempt.get("head") and head != attempt["head"]:
        raise ValueError("Queued branch head changed unexpectedly")
    verify_commit(repo, head, attempt, bot_id)
    return head
