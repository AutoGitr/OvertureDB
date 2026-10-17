"""The bot commits only dataset files, and keeps state off main."""

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
def clone(origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The bot's checkout of *origin*, one commit on main."""
    root = tmp_path / "clone"
    github.run("git", "clone", "-q", str(origin), str(root))
    monkeypatch.setattr(github, "ROOT", root)
    github.git("config", "user.name", "Test")
    github.git("config", "user.email", "test@example.com")
    github.git("config", "commit.gpgsign", "false")
    github.git("commit", "-q", "--allow-empty", "-m", "base")
    github.git("push", "-q", "origin", "HEAD:main")
    return root


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
