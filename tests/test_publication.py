"""The publication boundary validates the exact candidate and fails closed."""

lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import MagicMock, patch

lazy import pytest

lazy from scripts import github, publication


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    github.run("git", "init", "-q", "-b", "main", cwd=root)
    github.run("git", "config", "user.name", "Test", cwd=root)
    github.run("git", "config", "user.email", "test@example.com", cwd=root)
    (root / "data/movies").mkdir(parents=True)
    (root / "data/movies/tmdb-1.json").write_text("old\n")
    (root / "code.txt").write_text("trusted\n")
    github.run("git", "add", ".", cwd=root)
    github.run(
        "git",
        "-c",
        "core.hooksPath=",
        "commit",
        "--no-gpg-sign",
        "-qm",
        "base",
        cwd=root,
    )
    github.run("git", "remote", "add", "origin", str(root), cwd=root)
    return root


def plan(_root: Path) -> publication.Commit:
    return (
        "title",
        "body",
        {"data/movies/tmdb-2.json": "new\n"},
        ["data/movies/tmdb-1.json"],
    )


@pytest.mark.parametrize("failure", ["", "guard", "mutation", "revoked", "api"])
def test_publication_checks_exact_candidate_before_commit(
    checkout: Path, failure: str
) -> None:
    base = github.run("git", "rev-parse", "HEAD", cwd=checkout)
    real_run = github.run
    checks: list[Path] = []

    def run(executable: str, *args: str, **kwargs: Any) -> str:
        if executable != "bash":
            return real_run(executable, *args, **kwargs)
        candidate: Path = kwargs["cwd"]
        checks.append(candidate)
        assert candidate != checkout
        assert (candidate / "data/movies/tmdb-2.json").read_text() == "new\n"
        assert not (candidate / "data/movies/tmdb-1.json").exists()
        assert (candidate / "code.txt").read_text() == "trusted\n"
        if failure == "guard":
            raise RuntimeError("guard failed")
        if failure == "mutation":
            (candidate / "data/movies/tmdb-2.json").write_text("mutated")
        return "all checks passed"

    def commit(*args: Any) -> str:
        assert len(checks) == 1
        assert args == ("o/r", "main", base, *plan(checkout))
        if failure == "api":
            raise RuntimeError("uncertain write")
        return "published"

    authorize = MagicMock(side_effect=[True, failure != "revoked"])
    with (
        patch.object(github, "run", side_effect=run),
        patch.object(github, "api", return_value={"object": {"sha": base}}),
        patch.object(github, "commit_files", side_effect=commit) as commits,
    ):
        if failure in {"guard", "mutation", "api"}:
            with pytest.raises(RuntimeError):
                publication.publish("o/r", checkout, plan, authorize)
        else:
            result = publication.publish("o/r", checkout, plan, authorize)
            assert result == (None if failure == "revoked" else "published")
        assert commits.call_count == (1 if failure in {"", "api"} else 0)
    assert len(checks) == 1
    assert not checks[0].exists()
    assert (checkout / "data/movies/tmdb-1.json").read_text() == "old\n"
    assert not (checkout / "data/movies/tmdb-2.json").exists()


@pytest.mark.parametrize("code_change", [False, True])
def test_main_movement_rebuilds_and_rechecks_only_for_dataset_changes(
    checkout: Path, code_change: bool
) -> None:
    initial = github.run("git", "rev-parse", "HEAD", cwd=checkout)
    real_run = github.run
    bases: list[str] = []
    current = initial

    def run(executable: str, *args: str, **kwargs: Any) -> str:
        nonlocal current
        if executable != "bash":
            return real_run(executable, *args, **kwargs)
        bases.append(real_run("git", "rev-parse", "HEAD", cwd=kwargs["cwd"]))
        if len(bases) == 1:
            target = "code.txt" if code_change else "data/movies/tmdb-3.json"
            (checkout / target).write_text("concurrent\n")
            real_run("git", "add", target, cwd=checkout)
            real_run(
                "git",
                "-c",
                "core.hooksPath=",
                "commit",
                "--no-gpg-sign",
                "-qm",
                "other",
                cwd=checkout,
            )
            current = real_run("git", "rev-parse", "HEAD", cwd=checkout)
        return "passed"

    def ref(_path: str) -> dict[str, Any]:
        return {"object": {"sha": current}}

    with (
        patch.object(github, "run", side_effect=run),
        patch.object(github, "api", side_effect=ref),
        patch.object(github, "commit_files", return_value="published") as commits,
    ):
        if code_change:
            with pytest.raises(RuntimeError, match="Main code changed"):
                publication.publish("o/r", checkout, plan, lambda: True)
            commits.assert_not_called()
        else:
            assert (
                publication.publish("o/r", checkout, plan, lambda: True) == "published"
            )
            assert bases == [initial, current]
            assert commits.call_args.args[2] == current


def test_no_changes_or_revoked_approval_never_runs_guard(checkout: Path) -> None:
    with patch.object(publication, "validate_candidate") as guard:
        assert (
            publication.publish("o/r", checkout, lambda _root: None, lambda: True)
            is None
        )
        assert publication.publish("o/r", checkout, plan, lambda: False) is None
        guard.assert_not_called()


def test_candidate_rejects_paths_outside_dataset(checkout: Path) -> None:
    with pytest.raises(ValueError, match="only modify dataset"):
        publication.validate_candidate(checkout, {"../outside": "bad"}, [])


def test_repeated_main_movement_has_bounded_retries(checkout: Path) -> None:
    with (
        patch.object(publication, "validate_candidate") as checks,
        patch.object(github, "api", return_value={"object": {"sha": "other"}}),
        patch.object(github, "commit_files") as commits,
    ):
        with pytest.raises(RuntimeError, match="Main kept changing"):
            publication.publish("o/r", checkout, plan, lambda: True)
        assert checks.call_count == 3
        commits.assert_not_called()
