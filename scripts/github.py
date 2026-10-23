"""GitHub CLI access, signed dataset commits, and off-main state branches."""

lazy import base64
lazy import json
lazy import re
lazy import shutil
lazy import subprocess
lazy import tempfile
lazy from pathlib import Path
lazy from typing import Any

lazy from schema.contract import ENTRY_FOLDERS

ROOT = Path(__file__).resolve().parents[1]

#: The account that commits every automated dataset change.
BOT_LOGIN = "overturedb[bot]"
STATE_FILE = "state.json"


def run(
    executable: str,
    *args: str,
    stdin: str | None = None,
    cwd: Path | None = None,
    timeout: int = 60,
) -> str:
    resolved = shutil.which(executable)
    if resolved is None:
        raise OSError(f"{executable} is required")
    # Internal executables and argument arrays; input is never evaluated by a shell.
    try:
        result = subprocess.run(  # noqa: S603
            [resolved, *args],
            cwd=cwd or ROOT,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{executable} exceeded its {timeout} second timeout"
        ) from exc
    if result.returncode:
        raise RuntimeError(
            "\n".join(
                part.strip() for part in (result.stdout, result.stderr) if part.strip()
            )
            or f"{executable} command failed"
        )
    return result.stdout.strip()


def gh(*args: str, payload: dict[str, Any] | None = None) -> str:
    if payload is None:
        return run("gh", *args)
    return run("gh", *args, "--input", "-", stdin=json.dumps(payload))


def api(
    path: str, payload: dict[str, Any] | None = None, *, method: str | None = None
) -> Any:
    """Call a REST endpoint and return its JSON, or ``None`` for an empty reply.

    ``gh`` sends a GET, or a POST when there is a *payload*, unless *method*
    names another.
    """
    output = gh("api", path, *(("--method", method) if method else ()), payload=payload)
    return json.loads(output) if output else None


def pages(path: str) -> list[dict[str, Any]]:
    result: list[list[dict[str, Any]]] = json.loads(
        gh("api", path, "--paginate", "--slurp")
    )
    return [item for page in result for item in page]


def git(*args: str) -> str:
    return run("git", *args)


def validate_dataset_path(path: str) -> None:
    folders = "|".join(ENTRY_FOLDERS.values())
    if not re.fullmatch(rf"data/({folders})/[\w-]+\.json", path):
        raise ValueError(f"Bot commits may only modify dataset entries: {path}")


def commit_files(
    repo: str,
    branch: str,
    expected_head: str,
    headline: str,
    body: str,
    additions: dict[str, str],
    deletions: list[str],
) -> str:
    """Create a GitHub-signed dataset commit on *branch* pinned to *expected_head*."""
    for path in (*additions, *deletions):
        validate_dataset_path(path)
    message: dict[str, str] = {"headline": headline}
    if body:
        message["body"] = body
    result = api(
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
                        "branchName": branch,
                    },
                    "expectedHeadOid": expected_head,
                    "message": message,
                    "fileChanges": {
                        "additions": [
                            {
                                "path": path,
                                "contents": base64.b64encode(
                                    content.encode("utf-8")
                                ).decode("ascii"),
                            }
                            for path, content in sorted(additions.items())
                        ],
                        "deletions": [{"path": path} for path in sorted(deletions)],
                    },
                }
            },
        },
    )
    if result.get("errors"):
        raise RuntimeError("GitHub rejected the signed commit mutation")
    return str(result["data"]["createCommitOnBranch"]["commit"]["oid"])


def load_state(branch: str) -> tuple[dict[str, Any], str | None]:
    """Return ``state.json`` from *branch* and its commit, or ``({}, None)``."""
    ref = f"refs/heads/{branch}"
    if not git("ls-remote", "origin", ref):
        return {}, None
    git("fetch", "--depth=1", "origin", ref)
    parent = git("rev-parse", "FETCH_HEAD")
    return json.loads(git("show", f"{parent}:{STATE_FILE}")), parent


def save_state(
    branch: str, state: dict[str, Any], parent: str | None, message: str
) -> None:
    """Commit *state* to *branch* on top of *parent*, leaving the work tree alone."""
    # Text-mode stdin would turn newlines into CRLF on Windows.
    with tempfile.TemporaryDirectory() as directory:
        content = Path(directory) / STATE_FILE
        content.write_text(
            json.dumps(state, indent=1, sort_keys=True) + "\n",
            newline="\n",
        )
        blob = git("hash-object", "-w", str(content))
    tree = run("git", "mktree", "-z", stdin=f"100644 blob {blob}\t{STATE_FILE}\0")
    git("config", "user.name", BOT_LOGIN)
    git("config", "user.email", f"{BOT_LOGIN}@users.noreply.github.com")
    parents = ("-p", parent) if parent else ()
    state_commit = git("commit-tree", tree, *parents, "-m", message)
    gh("auth", "setup-git")
    git(
        "push",
        f"--force-with-lease=refs/heads/{branch}:{parent or ''}",
        "origin",
        f"{state_commit}:refs/heads/{branch}",
    )
