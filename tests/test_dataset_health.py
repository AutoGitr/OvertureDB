"""The health check must check few entries at a time and report what it finds."""

lazy import io
lazy from datetime import UTC, datetime
lazy from email.message import Message
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import MagicMock, patch
lazy from urllib.error import HTTPError

lazy import pytest

lazy from scripts import dataset_health as health
lazy from scripts import github
lazy from tests.test_catalog import movie

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)


def http_error(code: int) -> HTTPError:
    return HTTPError("https://example.test", code, "error", Message(), io.BytesIO())


def files(**entries: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    return {
        f"data/movies/{name}.json": (f"hash-{name}", entry)
        for name, entry in entries.items()
    }


def test_changed_problem_entries_are_extra_and_checked_even_with_zero_limit() -> None:
    known: dict[str, health.EntryState] = {
        "fixed": {"checked": "2026-10-12", "hash": "before", "problems": ["dead"]},
        "older_fix": {
            "checked": "2026-01-01",
            "hash": "before",
            "problems": ["dead"],
        },
        "unchanged": {"checked": "2026-01-01", "hash": "h", "problems": ["dead"]},
        "healthy": {"checked": "2026-01-01", "hash": "before", "problems": []},
        "deleted": {"checked": "2026-01-01", "hash": "h", "problems": ["dead"]},
    }
    hashes = {
        "new": "h",
        "fixed": "after",
        "older_fix": "after",
        "unchanged": "h",
        "healthy": "after",
    }
    assert health.select_entries(hashes, known, 0) == [
        "fixed",
        "older_fix",
    ]
    assert health.select_entries(hashes, known, 2) == [
        "fixed",
        "older_fix",
        "healthy",
        "new",
    ]


def test_negative_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="zero or greater"):
        health.select_entries({}, {}, -1)


def test_new_and_changed_entries_come_before_the_oldest_checked() -> None:
    known: dict[str, health.EntryState] = {
        "old": {"checked": "2026-01-01", "hash": "h", "problems": []},
        "recent": {"checked": "2026-10-01", "hash": "h", "problems": []},
        "changed": {"checked": "2026-10-12", "hash": "before", "problems": []},
    }
    hashes = {"recent": "h", "old": "h", "changed": "after", "new": "h"}
    assert health.select_entries(hashes, known, 3) == ["changed", "new", "old"]
    assert health.select_entries(hashes, known, 10)[-1] == "recent"


@patch.object(health, "check_art_url")
def test_artwork_reports_dead_links_ratio_and_resolution(
    probe: MagicMock,
    subtests: pytest.Subtests,
) -> None:
    for entry, result, expected in (
        (movie(), (2000, 3000), None),
        (movie(), (1000, 1500), None),
        (movie(), (800, 1200), "800x1200 is below 1000x1500"),
        (movie(), (1000, 1490), "1000x1490 is below 1000x1500"),
        (
            movie(
                poster_url=None,
                background_url="https://image.tmdb.org/t/p/original/bg.jpg",
            ),
            (1600, 900),
            None,
        ),
        (
            movie(
                poster_url=None,
                background_url="https://image.tmdb.org/t/p/original/bg.jpg",
            ),
            (1280, 720),
            "1280x720 is below 1600x900",
        ),
        (
            movie(
                poster_url=None,
                background_url="https://image.tmdb.org/t/p/original/bg.jpg",
            ),
            (1600, 895),
            "1600x895 is below 1600x900",
        ),
        (movie(), (1000, 1000), "outside 1%"),
        (movie(), http_error(404), "HTTP 404"),
        (movie(), ValueError("not a JPEG"), "not a JPEG"),
        (movie(), None, None),
    ):
        with subtests.test(result=result, expected=expected):
            probe.side_effect = [result]
            problems = health.artwork_problems(entry)
            if expected is None:
                assert problems == []
            else:
                assert len(problems) == 1
                assert expected in problems[0]


@patch.object(health, "check_art_url")
def test_rate_limits_and_outages_are_retried_later(
    probe: MagicMock, subtests: pytest.Subtests
) -> None:
    for error in (http_error(429), http_error(503), TimeoutError("slow")):
        with subtests.test(error=error):
            probe.side_effect = [error]
            with pytest.raises(health.TransientError):
                health.artwork_problems(movie())


@patch.object(health, "urlopen")
def test_theme_availability_uses_oembed(urlopen: MagicMock) -> None:
    assert health.theme_problem("4xdyx5NVUhI") is None
    assert "4xdyx5NVUhI" in urlopen.call_args.args[0].full_url
    assert urlopen.call_args.args[0].full_url.startswith(
        "https://www.youtube.com/oembed?"
    )
    for code, expected in ((404, "removed"), (401, "private or not embeddable")):
        urlopen.side_effect = http_error(code)
        assert health.theme_problem("4xdyx5NVUhI") == expected
    urlopen.side_effect = http_error(500)
    with pytest.raises(health.TransientError):
        health.theme_problem("4xdyx5NVUhI")


@patch.object(health, "entry_problems")
def test_fix_rechecks_clear_resolved_problems_and_keep_transient_failures(
    problems: MagicMock,
) -> None:
    state: health.State = {
        "entries": {
            f"data/movies/{name}.json": {
                "checked": "2026-01-01",
                "hash": "before",
                "problems": ["poster: HTTP 404"],
            }
            for name in ("a", "b")
        }
    }
    entries = files(a=movie(), b=movie(tmdb_id=2), c=movie(tmdb_id=3))
    problems.side_effect = [[], health.TransientError("slow")]
    result = health.check_health(state, entries, NOW, limit=0)
    assert problems.call_count == 2
    assert result["entries"]["data/movies/a.json"]["problems"] == []
    assert result["entries"]["data/movies/a.json"]["hash"] == "hash-a"
    assert (
        result["entries"]["data/movies/b.json"]
        == state["entries"]["data/movies/b.json"]
    )
    assert "data/movies/c.json" not in result["entries"]
    problems.reset_mock(side_effect=True)
    problems.return_value = []
    retried = health.check_health(result, entries, NOW, limit=0)
    problems.assert_called_once_with(entries["data/movies/b.json"][1])
    assert retried["entries"]["data/movies/b.json"]["problems"] == []


@patch.object(health, "entry_problems")
def test_health_records_results_and_keeps_retries_for_next_run(
    problems: MagicMock,
) -> None:
    state = health.empty_state()
    state["entries"] = {
        "data/movies/a.json": {
            "checked": "2026-01-01",
            "hash": "hash-a",
            "problems": ["poster: HTTP 404"],
        },
        "data/movies/gone.json": {"checked": "x", "hash": "y", "problems": []},
    }
    # b is new, so it is checked before a.
    problems.side_effect = [["theme: removed"], health.TransientError("slow")]
    result = health.check_health(
        state,
        files(a=movie(), b=movie(tmdb_id=2)),
        NOW,
        limit=10,
    )
    assert (
        result["entries"]["data/movies/a.json"]
        == state["entries"]["data/movies/a.json"]
    )
    assert result["entries"]["data/movies/b.json"] == {
        "checked": "2026-10-13",
        "hash": "hash-b",
        "problems": ["theme: removed"],
    }
    assert "data/movies/gone.json" not in result["entries"]


def test_report_describes_the_selected_rotation_limit() -> None:
    body = health.render(health.empty_state(), {}, limit=0)
    assert "all changed entries with reported problems" in body
    assert "up to 0 entries" in body
    assert "None found." in body


def test_report_lists_problems_and_stays_within_issue_limit() -> None:
    state = health.empty_state()
    entries = {"data/movies/a.json": movie()}
    for index in range(2000):
        path = f"data/movies/tmdb-{index}.json"
        entries[path] = movie(tmdb_id=index + 2)
        state["entries"][path] = {
            "checked": "2026-10-13",
            "hash": "h",
            "problems": ["poster https://image.tmdb.org/t/p/original/x.jpg: " * 3],
        }
    body = health.render(state, entries)
    assert body.startswith(health.HEALTH_MARKER)
    assert "`data/movies/tmdb-0.json`" in body
    assert "more entries" in body
    assert len(body) <= health.MAX_ISSUE_BODY


@patch.object(health, "api")
@patch.object(health, "pages")
def test_report_updates_the_bot_issue_and_ignores_lookalikes(
    pages: MagicMock, api: MagicMock
) -> None:
    lookalike: dict[str, Any] = {
        "number": 1,
        "user": {"login": "someone"},
        "body": health.HEALTH_MARKER,
    }
    pages.return_value = [lookalike]
    health.publish_report("owner/repo", "report")
    assert api.call_args.args[0] == "repos/owner/repo/issues"
    assert api.call_args.args[1]["labels"] == [health.HEALTH_LABEL]
    pages.return_value = [
        lookalike,
        {
            "number": 2,
            "user": {"login": github.BOT_LOGIN},
            "body": lookalike["body"],
        },
    ]
    health.publish_report("owner/repo", "report")
    assert api.call_args.args[0] == "repos/owner/repo/issues/2"
    assert api.call_args.kwargs["method"] == "PATCH"
    api.reset_mock()
    health.publish_report("owner/repo", lookalike["body"])
    api.assert_not_called()


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Stub everything main reaches beyond the dataset; return the stubs."""
    entry = tmp_path / "data/movies/tmdb-1.json"
    entry.parent.mkdir(parents=True)
    entry.write_text("{}")
    stubs = {
        "load_state": MagicMock(return_value=({}, "parent-sha")),
        "dataset": MagicMock(return_value=[(entry, movie())]),
        "entry_problems": MagicMock(return_value=["poster: HTTP 404"]),
        "publish_report": MagicMock(),
        "save_state": MagicMock(),
    }
    for name, stub in stubs.items():
        monkeypatch.setattr(health, name, stub)
    monkeypatch.setattr(health, "ROOT", tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    return stubs


def test_a_dry_run_prints_the_report_and_changes_nothing(
    run: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["dataset_health.py", "--dry-run", "--limit", "5"])

    assert health.main() == 0

    report = capsys.readouterr().out
    assert "up to 5 entries" in report
    assert "poster: HTTP 404" in report
    run["publish_report"].assert_not_called()
    run["save_state"].assert_not_called()


def test_a_run_publishes_the_report_and_saves_what_it_learned(
    run: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["dataset_health.py"])

    assert health.main() == 0

    repo, report = run["publish_report"].call_args.args
    assert (repo, "poster: HTTP 404" in report) == ("owner/repo", True)
    branch, state, parent, _message = run["save_state"].call_args.args
    assert (branch, parent) == (health.STATE_BRANCH, "parent-sha")
    assert state["entries"]["data/movies/tmdb-1.json"]["problems"] == [
        "poster: HTTP 404"
    ]


def test_a_run_that_learns_nothing_saves_no_state(
    run: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.argv", ["dataset_health.py", "--limit", "0"])

    assert health.main() == 0

    run["publish_report"].assert_called_once()
    run["save_state"].assert_not_called()


def test_a_failed_run_reports_why(
    run: dict[str, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.argv", ["dataset_health.py"])
    run["load_state"].side_effect = RuntimeError("state branch unreadable")

    assert health.main() == 1

    assert "state branch unreadable" in capsys.readouterr().err
