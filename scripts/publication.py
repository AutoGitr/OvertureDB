"""Validate isolated candidates before publishing, retrying dataset-only races."""

lazy import hashlib
lazy import tempfile
lazy from collections.abc import Callable
lazy from pathlib import Path

lazy from . import github

type Commit = tuple[str, str, dict[str, str], list[str]]


def _snapshot(root: Path, additions: dict[str, str]) -> dict[str, str]:
    tracked = github.run("git", "ls-files", "-z", cwd=root).split("\0")
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in set(tracked)
        | additions.keys()
        | {
            path.relative_to(root).as_posix()
            for path in (root / "data").rglob("*.json")
        }
        if name and (root / name).is_file()
    }


def validate_candidate(
    root: Path, additions: dict[str, str], deletions: list[str]
) -> None:
    """Apply only dataset changes and require the complete guard to succeed."""
    for name in (*additions, *deletions):
        github.validate_dataset_path(name)
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Candidate path must stay in its checkout: {name}")
    for name in deletions:
        (root / name).unlink()
    for name, content in additions.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    expected = _snapshot(root, additions)
    output = github.run("bash", "scripts/contribution-check.sh", cwd=root, timeout=300)
    print(output)  # noqa: T201 -- Preserve the validation report in Actions logs.
    if _snapshot(root, additions) != expected:
        raise RuntimeError(
            "Contribution Guard modified the candidate; publication stopped"
        )


def publish(
    repo: str,
    root: Path,
    prepare: Callable[[Path], Commit | None],
    authorize: Callable[[], bool],
) -> str | None:
    """Rebuild and recheck at most three times; never retry an uncertain write."""
    initial = github.run("git", "rev-parse", "HEAD", cwd=root)
    base = initial
    for _attempt in range(3):
        with tempfile.TemporaryDirectory(prefix="overturedb-candidate-") as directory:
            candidate = Path(directory) / "checkout"
            github.run(
                "git", "clone", "--shared", "--no-checkout", str(root), str(candidate)
            )
            github.run("git", "checkout", "--detach", base, cwd=candidate)
            commit = prepare(candidate)
            if commit is None or not authorize():
                return None
            headline, body, additions, deletions = commit
            validate_candidate(candidate, additions, deletions)
            if not authorize():
                return None
            live = github.api(f"repos/{repo}/git/ref/heads/main")["object"]["sha"]
            if live == base:
                # CAS closes the race between the ref read and the mutation.
                return github.commit_files(
                    repo, "main", base, headline, body, additions, deletions
                )
        github.run("git", "fetch", "--no-tags", "origin", "main", cwd=root)
        base = github.run("git", "rev-parse", "FETCH_HEAD", cwd=root)
        changed = github.run("git", "diff", "--name-only", initial, base, cwd=root)
        if any(not name.startswith("data/") for name in changed.splitlines()):
            raise RuntimeError(
                "Main code changed during validation; rerun the workflow"
            )
    raise RuntimeError("Main kept changing during validation; rerun the workflow")
