"""The bot commits only dataset files, and keeps state off main."""

lazy import base64
lazy import subprocess
lazy from pathlib import Path
lazy from unittest.mock import MagicMock, patch

lazy import pytest

lazy from scripts import github


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    github.run("git", "init", "-q", "--bare", "-b", "main", str(origin))
    return origin


@pytest.fixture
def state_checkout(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh checkout of *origin* without any commit of its own."""
    root = tmp_path / "clone"
    github.run("git", "clone", "-q", str(origin), str(root))
    monkeypatch.setattr(github, "ROOT", root)
    github.git("config", "commit.gpgsign", "false")


@pytest.mark.usefixtures("state_checkout")
@patch.object(github, "gh", return_value="")
def test_state_round_trips_on_its_own_branch(_gh: MagicMock, origin: Path) -> None:
    assert github.load_state("state/a") == ({}, None)
    github.save_state("state/a", {"revision": "1"}, None, "first")
    github.save_state("state/b", {"other": True}, None, "other workflow")
    state, parent = github.load_state("state/a")
    assert state == {"revision": "1"}
    github.save_state("state/a", {"revision": "2"}, parent, "second")
    state, head = github.load_state("state/a")
    assert state == {"revision": "2"}
    assert github.load_state("state/b")[0] == {"other": True}
    history = github.run("git", "--git-dir", str(origin), "rev-parse", f"{head}~1")
    assert history == parent
    assert github.git("status", "--porcelain") == ""
    assert github.git("branch", "--list") == ""


@patch.object(github, "api")
def test_commit_files_builds_signed_graphql_mutation_and_rejects_non_dataset_paths(
    api: MagicMock,
) -> None:
    api.return_value = {"data": {"createCommitOnBranch": {"commit": {"oid": "abc123"}}}}
    oid = github.commit_files(
        "AutoGitr/OvertureDB",
        "main",
        "base-sha",
        "Add movie: Alien (1979) (#1)",
        "Closes #1",
        {"data/movies/tmdb-1.json": '{"title": "Alien"}\n'},
        ["data/movies/imdb-tt1.json"],
    )
    assert oid == "abc123"
    variables = api.call_args.args[1]["variables"]["input"]
    assert variables["branch"] == {
        "repositoryNameWithOwner": "AutoGitr/OvertureDB",
        "branchName": "main",
    }
    assert variables["expectedHeadOid"] == "base-sha"
    assert variables["message"] == {
        "headline": "Add movie: Alien (1979) (#1)",
        "body": "Closes #1",
    }
    assert variables["fileChanges"] == {
        "additions": [
            {
                "path": "data/movies/tmdb-1.json",
                "contents": base64.b64encode(b'{"title": "Alien"}\n').decode("ascii"),
            }
        ],
        "deletions": [{"path": "data/movies/imdb-tt1.json"}],
    }
    for bad in ("README.md", "data/movies/../evil.json", "scripts/github.py"):
        with pytest.raises(ValueError, match="only modify dataset entries"):
            github.commit_files(
                "AutoGitr/OvertureDB", "main", "base", "msg", "", {bad: "{}"}, []
            )
    api.return_value = {"errors": [{"message": "stale head"}]}
    with pytest.raises(RuntimeError, match="rejected the signed commit"):
        github.commit_files(
            "AutoGitr/OvertureDB",
            "main",
            "base",
            "msg",
            "",
            {"data/movies/tmdb-1.json": "{}"},
            [],
        )


@patch.object(github, "run")
def test_api_and_pages_parse_gh_output(run: MagicMock) -> None:
    run.return_value = ""
    assert github.api("repos/o/r", {"a": 1}, method="PATCH") is None
    run.return_value = '[[{"id": 1}], [{"id": 2}]]'
    assert github.pages("repos/o/r/issues") == [{"id": 1}, {"id": 2}]


@patch.object(github.shutil, "which", return_value="bash")
@patch.object(
    github.subprocess, "run", side_effect=subprocess.TimeoutExpired("bash", 1)
)
def test_command_timeout_is_a_publication_failure(
    _run: MagicMock, _which: MagicMock
) -> None:
    with pytest.raises(RuntimeError, match="exceeded its 1 second timeout"):
        github.run("bash", "scripts/contribution-check.sh", timeout=1)


def test_dataset_paths_cover_every_entry_folder() -> None:
    for path in (
        "data/movies/tmdb-1.json",
        "data/shows/tvdb-2.json",
        "data/collections/tmdb-10.json",
    ):
        github.validate_dataset_path(path)
    with pytest.raises(ValueError, match="only modify dataset entries"):
        github.validate_dataset_path("data/people/tmdb-1.json")
