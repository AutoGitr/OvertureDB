"""Only maintainers change the dataset through pull requests."""

lazy import json
lazy from pathlib import Path
lazy from unittest.mock import MagicMock, patch

lazy import pytest

lazy from scripts import guard

DATA = ["README.md", "data/movies/tmdb-1.json"]


def test_maintainers_may_change_the_dataset(subtests: pytest.Subtests) -> None:
    for association in sorted(guard.MAINTAINERS):
        with subtests.test(association=association):
            guard.validate_changes({"author_association": association}, DATA)


def test_others_may_change_everything_but_the_dataset(
    subtests: pytest.Subtests,
) -> None:
    guard.validate_changes({"author_association": "NONE"}, ["README.md"])
    for association in ("COLLABORATOR", "CONTRIBUTOR", "NONE"):
        with subtests.test(association=association), pytest.raises(ValueError):
            guard.validate_changes({"author_association": association}, DATA)


def _pull_request_event(tmp_path: Path, association: str) -> Path:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps(
            {
                "pull_request": {
                    "author_association": association,
                    "base": {"sha": "base"},
                    "head": {"sha": "head"},
                }
            }
        )
    )
    return event


@patch.object(guard, "git", return_value="README.md\0data/movies/tmdb-1.json\0")
def test_a_pull_request_is_checked_against_its_merge_base_diff(
    git: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(_pull_request_event(tmp_path, "NONE")))

    with pytest.raises(ValueError, match="maintainers"):
        guard.main()

    git.assert_called_once_with(
        "diff", "--name-only", "--no-renames", "-z", "base...head"
    )


@patch.object(guard, "git")
def test_other_events_are_not_checked(
    git: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    guard.main()

    git.assert_not_called()
