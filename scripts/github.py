"""GitHub CLI access, and how the bot commits dataset changes and keeps state."""

lazy import json
lazy import os
lazy import shutil
lazy import subprocess
lazy import tempfile
lazy from pathlib import Path
lazy from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: The account that commits every dataset change.
BOT_LOGIN = "overturedb[bot]"
STATE_FILE = "state.json"


class MissingResourceError(ValueError):
    """A previously recorded issue, approval, branch or PR no longer exists."""


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


def api(
    path: str, payload: dict[str, Any] | None = None, *, method: str | None = None
) -> Any:
    """Call a REST endpoint and return its JSON, or ``None`` for an empty reply.

    ``gh`` sends a GET, or a POST when there is a *payload*, unless *method*
    names another.
    """
    try:
        output = gh(
            "api", path, *(("--method", method) if method else ()), payload=payload
        )
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            raise MissingResourceError(
                f"Recorded GitHub resource is missing: {path}"
            ) from exc
        raise
    return json.loads(output) if output else None


def pages(path: str) -> list[dict[str, Any]]:
    result: list[list[dict[str, Any]]] = json.loads(
        gh("api", path, "--paginate", "--slurp")
    )
    return [item for page in result for item in page]


def set_output(name: str, value: str) -> None:
    """Pass *value* to later workflow steps as ``steps.<id>.outputs.<name>``."""
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"{name}={value}\n")


def git(*args: str) -> str:
    return run("git", *args)


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
