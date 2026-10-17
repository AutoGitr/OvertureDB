"""Real temporary Git repositories verify exact blobs, leases and branch recovery."""

lazy import base64
lazy import json
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import MagicMock

lazy import pytest

lazy from scripts import github, queue_git, queue_prs
lazy from scripts.catalog import entry_json, write_entry_json
lazy from scripts.changes import file_changes
lazy from scripts.queue_state import Store
lazy from tests.test_catalog import movie


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    origin = tmp_path / "origin.git"
    github.run("git", "init", "--bare", "-b", "main", str(origin))
    root = tmp_path / "checkout"
    github.run("git", "clone", str(origin), str(root))
    monkeypatch.setattr(github, "ROOT", root)
    github.git("config", "user.name", "Test")
    github.git("config", "user.email", "test@example.com")
    github.git("config", "commit.gpgsign", "false")
    write_entry_json(root / "data/movies/tmdb-1.json", movie())
    github.git("add", "data")
    github.git("commit", "-m", "base")
    github.git("push", "origin", "HEAD:main")
    monkeypatch.setattr(github, "gh", MagicMock())
    return root


def test_real_state_cas_and_health_independence(repository: Path) -> None:
    left, right = Store(), Store()
    left.enqueue("import", {"upstream": "a" * 40})
    with pytest.raises(RuntimeError):
        right.enqueue("import", {"upstream": "b" * 40})
    github.save_state("state/health", {"health": "unchanged"}, None, "health")
    assert github.load_state("state/health")[0] == {"health": "unchanged"}
    assert Store().state == left.state
    before = github.git("ls-remote", "origin", "main")
    left.enqueue("import", {"upstream": "c" * 40})
    assert github.git("ls-remote", "origin", "main") == before


def test_snapshots_and_full_signed_commit_provenance(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = github.git("rev-parse", "HEAD")
    assert queue_git.snapshot(base) == [movie()]
    monkeypatch.setattr(
        github, "api", MagicMock(return_value={"object": {"sha": base}})
    )
    assert queue_git.main_snapshot("owner/db") == (base, [movie()])
    with pytest.raises(ValueError, match="pinned"):
        queue_git.snapshot("main")
    write_entry_json(repository / "data/movies/tmdb-1.json", movie(year=2025))
    github.git("add", "data")
    github.git("commit", "-m", "change", "-m", "audit")
    head = github.git("rev-parse", "HEAD")
    github.git("push", "origin", "HEAD:automation/test")
    attempt: dict[str, Any] = {
        "base": base,
        "audit": "audit",
        "branch": "automation/test",
        "files": file_changes([movie()], [movie(year=2025)]),
    }
    metadata: dict[str, Any] = {
        "author": {"id": 99},
        "parents": [{"sha": base}],
        "commit": {"verification": {"verified": True}, "message": "change\n\naudit"},
    }
    monkeypatch.setattr(github, "api", MagicMock(return_value=metadata))
    queue_git.verify_commit("owner/db", head, attempt, 99)
    metadata["commit"]["verification"]["verified"] = False
    with pytest.raises(ValueError, match="signature"):
        queue_git.verify_commit("owner/db", head, attempt, 99)
    metadata["commit"]["verification"]["verified"] = True
    attempt["files"]["data/movies/tmdb-1.json"] += "\n"
    with pytest.raises(ValueError, match="content"):
        queue_git.verify_commit("owner/db", head, attempt, 99)
    attempt["files"] = {"data/movies/tmdb-1.json": None}
    with pytest.raises(ValueError, match="deletion"):
        queue_git.verify_commit("owner/db", head, attempt, 99)
    attempt["files"] = {"extra.py": "evil"}
    with pytest.raises(ValueError, match="unexpected files"):
        queue_git.verify_commit("owner/db", head, attempt, 99)


def test_signed_mutation_pins_parent_and_encodes_only_generated_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = MagicMock(
        return_value={"data": {"createCommitOnBranch": {"commit": {"oid": "signed"}}}}
    )
    monkeypatch.setattr(github, "api", api)
    attempt = {
        "branch": "automation/x",
        "base": "base",
        "audit": "request identity",
        "files": {
            "data/movies/tmdb-1.json": entry_json(movie()),
            "data/movies/tmdb-2.json": None,
        },
    }
    assert queue_git.signed_commit("owner/db", attempt, "Title") == "signed"
    sent = api.call_args.args[1]["variables"]["input"]
    assert sent["expectedHeadOid"] == "base"
    assert sent["branch"]["branchName"] == "automation/x"
    assert (
        json.loads(base64.b64decode(sent["fileChanges"]["additions"][0]["contents"]))
        == movie()
    )
    assert sent["fileChanges"]["deletions"] == [{"path": "data/movies/tmdb-2.json"}]
    api.return_value = {"errors": [{"message": "head changed"}]}
    with pytest.raises(RuntimeError, match="rejected"):
        queue_git.signed_commit("owner/db", attempt, "Title")


def test_import_fetches_exact_revision_and_preserves_curated_values(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream = repository.parent / "upstream"
    github.git("init", "-q", str(upstream))
    for key, value in (
        ("user.name", "Upstream"),
        ("user.email", "upstream@example.com"),
        ("commit.gpgsign", "false"),
    ):
        github.git("-C", str(upstream), "config", key, value)
    movies = upstream / "movies/themoviedb"
    shows = upstream / "tv_shows/themoviedb"
    movies.mkdir(parents=True)
    shows.mkdir(parents=True)
    (shows / ".keep").write_text("")
    (movies / "1.json").write_text(
        json.dumps({"id": 1, "title": "Upstream", "youtube_theme_url": "12345678901"})
    )
    github.git("-C", str(upstream), "add", ".")
    github.git("-C", str(upstream), "commit", "-m", "pinned")
    revision = github.git("-C", str(upstream), "rev-parse", "HEAD")
    real_git = github.git

    def local_fetch(*args: str) -> str:
        args = tuple(
            str(upstream) if a == "https://github.com/LizardByte/ThemerrDB.git" else a
            for a in args
        )
        return real_git(*args)

    monkeypatch.setattr(github, "git", local_fetch)
    curated = movie(youtube_id_overturedb="AB96CvvLZKc")
    result = queue_git.import_snapshot([curated], revision)
    assert result == [{**curated, "youtube_id_themerrdb": "12345678901"}]
    with pytest.raises(ValueError, match="immutable"):
        queue_git.import_snapshot([curated], "database")
    monkeypatch.setattr(
        queue_git,
        "import_themerrdb",
        MagicMock(return_value=({"skipped_error": 1}, [])),
    )
    with pytest.raises(ValueError, match="validation"):
        queue_git.import_snapshot([curated], revision)


def test_publication_requires_strict_signed_rules_without_app_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules: list[dict[str, Any]] = [
        {"type": "pull_request", "ruleset_id": 1},
        {"type": "required_signatures", "ruleset_id": 1},
        {
            "type": "required_status_checks",
            "ruleset_id": 1,
            "parameters": {
                "strict_required_status_checks_policy": True,
                "required_status_checks": [{"context": "contribution-guard"}],
            },
        },
    ]
    pages = MagicMock(return_value=rules)
    api = MagicMock(return_value={"bypass_actors": []})
    monkeypatch.setattr(github, "pages", pages)
    monkeypatch.setattr(github, "api", api)
    queue_prs.protections("owner/db", 42)
    api.return_value = {
        "bypass_actors": [{"actor_type": "Integration", "actor_id": 42}]
    }
    with pytest.raises(ValueError, match="bypass"):
        queue_prs.protections("owner/db", 42)
    rules[2]["parameters"]["strict_required_status_checks_policy"] = False
    with pytest.raises(ValueError, match="up-to-date"):
        queue_prs.protections("owner/db", 42)
    pages.return_value = []
    with pytest.raises(ValueError, match="signed"):
        queue_prs.protections("owner/db", 42)
