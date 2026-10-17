"""Deterministic GitHub simulation exercises durable lifecycle and recovery."""

lazy import copy
lazy import json
lazy from collections.abc import Callable
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import MagicMock

lazy import pytest

lazy from scripts import (
    automation,
    contribution_queue,
    github,
    guard,
    queue_git,
    queue_issues,
    queue_prs,
)
lazy from scripts.changes import digest
lazy from scripts.queue_state import Store
lazy from tests.test_automation import issue, write_archive
lazy from tests.test_catalog import movie

REPO = "owner/db"


def imported_entries(entries: list[dict[str, Any]], _: str) -> list[dict[str, Any]]:
    return [*entries, movie(tmdb_id=2)]


def unchanged_entries(entries: list[dict[str, Any]], _: str) -> list[dict[str, Any]]:
    return entries


def archive_writer(*entries: dict[str, Any]) -> Callable[[str, Path], None]:
    def write(_: str, path: Path) -> None:
        write_archive(path, *entries)

    return write


class GitHub:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.state: dict[str, Any] = {}
        self.revision: str | None = None
        self.base = "a" * 40
        self.entries = [movie()]
        self.issues: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[dict[str, Any]]] = {}
        self.prs: dict[int, dict[str, Any]] = {}
        self.refs: dict[str, str] = {}
        self.generated: dict[str, dict[str, Any]] = {}
        self.clock = 0
        self.permission = "write"
        self.check = "pending"
        self.merge_allowed = True
        self.events: list[dict[str, Any]] = []
        self.edited: str | None = None
        self.commit_verifier = MagicMock()
        monkeypatch.setattr(github, "api", self.api)
        monkeypatch.setattr(github, "pages", self.pages)
        monkeypatch.setattr(github, "load_state", self.load)
        monkeypatch.setattr(github, "save_state", self.save)
        monkeypatch.setattr(github, "gh", MagicMock())
        monkeypatch.setattr(github, "git", self.git)
        monkeypatch.setattr(queue_git, "signed_commit", self.commit)
        monkeypatch.setattr(queue_git, "verify_commit", self.commit_verifier)
        monkeypatch.setattr(
            queue_git,
            "main_snapshot",
            self.snapshot,
        )
        monkeypatch.setattr(automation, "check_artwork", MagicMock())

    def snapshot(self, _: str) -> tuple[str, list[dict[str, Any]]]:
        return self.base, copy.deepcopy(self.entries)

    def time(self) -> str:
        self.clock += 1
        return f"2026-10-17T00:{self.clock // 60:02}:{self.clock % 60:02}Z"

    def load(self, _: str) -> tuple[dict[str, Any], str | None]:
        return copy.deepcopy(self.state), self.revision

    def save(
        self, _: str, state: dict[str, Any], parent: str | None, message: str
    ) -> None:
        if parent != self.revision:
            raise RuntimeError("CAS rejected")
        self.state = copy.deepcopy(state)
        self.revision = self.time()

    def add_issue(
        self, number: int, *, tmdb_id: int = 1, title: str = "Changed"
    ) -> None:
        self.issues[number] = issue(
            number=number,
            body=(
                f"### Title\n{title}\n### TMDB ID\n{tmdb_id}\n"
                "### YouTube theme video ID\nAB96CvvLZKc\n"
                "### Reason for modification\nReviewed correction\n"
            ),
        )
        self.comments[number] = []

    def comment(self, number: int, body: str, actor: int = 7) -> dict[str, Any]:
        now = self.time()
        item = {
            "id": self.clock,
            "body": body,
            "created_at": now,
            "updated_at": now,
            "user": {
                "login": "maintainer" if actor == 7 else github.BOT_LOGIN,
                "id": actor,
            },
        }
        self.comments[number].append(item)
        return item

    def git(self, *args: str) -> str:
        if args[0] == "push":
            sha, ref = args[-1].split(":")
            self.refs[ref.removeprefix("refs/heads/")] = sha
        return ""

    def commit(self, _: str, attempt: dict[str, Any], title: str) -> str:
        head = digest(
            {"base": self.base, "files": attempt["files"], "time": self.time()}
        )[:40]
        self.refs[attempt["branch"]] = head
        self.generated[head] = copy.deepcopy(attempt)
        for pr in self.prs.values():
            if pr["head"]["ref"] == attempt["branch"]:
                pr["head"]["sha"] = head
                pr["merge_commit_sha"] = head
        return head

    def pages(self, path: str) -> list[dict[str, Any]]:
        if "/timeline?" in path:
            return self.events
        if "/comments?" in path:
            return copy.deepcopy(self.comments[int(path.split("/")[4])])
        if "/issues?" in path:
            return copy.deepcopy(
                [i for i in self.issues.values() if i["state"] == "open"]
            )
        if "/matching-refs/" in path:
            return [
                {"ref": f"refs/heads/{branch}", "object": {"sha": head}}
                for branch, head in self.refs.items()
            ]
        if "/pulls?" in path:
            branch = path.split(":", 1)[1].split("&", 1)[0]
            return [p for p in self.prs.values() if p["head"]["ref"] == branch]
        if "/files?" in path:
            pr = self.prs[int(path.split("/")[4])]
            return [{"filename": f} for f in self.generated[pr["head"]["sha"]]["files"]]
        raise AssertionError(path)

    def api(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        method: str | None = None,
    ) -> Any:
        if path == "graphql":
            return {"data": {"repository": {"issue": {"lastEditedAt": self.edited}}}}
        if path.startswith("users/"):
            return {"id": 99, "type": "Bot"}
        if "/permission" in path:
            return {"permission": self.permission}
        if path.endswith("commits/database"):
            return {"sha": "f" * 40}
        if "/check-runs?" in path:
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "contribution-guard",
                        "app": {"slug": "github-actions"},
                        "status": "in_progress"
                        if self.check == "pending"
                        else "completed",
                        "conclusion": None if self.check == "pending" else self.check,
                    }
                ],
            }
        if path.endswith("/git/refs"):
            assert payload
            self.refs[payload["ref"].removeprefix("refs/heads/")] = payload["sha"]
            return {}
        if "/issues/comments/" in path:
            comment = next(
                c
                for comments in self.comments.values()
                for c in comments
                if c["id"] == int(path.split("/")[-1])
            )
            if payload:
                comment.update(payload, updated_at=self.time())
            return copy.deepcopy(comment)
        if path.endswith("/comments"):
            assert payload
            return self.comment(int(path.split("/")[-2]), payload["body"], 99)
        if "/issues/" in path:
            item = self.issues[int(path.split("/")[-1])]
            if payload:
                item.update(payload)
            return copy.deepcopy(item)
        return self.pull_api(path, payload)

    def pull_api(self, path: str, payload: dict[str, Any] | None) -> Any:
        if path.endswith("/pulls"):
            assert payload
            number = len(self.prs) + 100
            head = self.refs[payload["head"]]
            self.prs[number] = {
                "number": number,
                "state": "open",
                "merged": False,
                "user": {"id": 99, "type": "Bot"},
                "head": {
                    "ref": payload["head"],
                    "sha": head,
                    "repo": {"full_name": REPO},
                },
                "base": {"ref": "main", "repo": {"full_name": REPO}},
                "changed_files": len(self.generated[head]["files"]),
                "merge_commit_sha": head,
                "mergeable_state": "clean",
                "auto_merge": None,
            }
            return copy.deepcopy(self.prs[number])
        if path.endswith("/merge"):
            pr = self.prs[int(path.split("/")[-2])]
            assert payload and payload["sha"] == pr["head"]["sha"]
            assert payload["merge_method"] == "squash"
            if not self.merge_allowed:
                return {"merged": False}
            assert self.check == "success"
            assert self.generated[payload["sha"]]["base"] == self.base
            pr.update(merged=True, state="closed")
            self.base = payload["sha"]
            entries = {e["tmdb_id"]: e for e in self.entries}
            for content in self.generated[self.base]["files"].values():
                if content:
                    entry = json.loads(content)
                    entries[entry["tmdb_id"]] = entry
            self.entries = list(entries.values())
            return {"merged": True, "sha": self.base}
        if "/pulls/" in path:
            pr = self.prs[int(path.split("/")[-1])]
            if payload:
                pr.update(payload)
            return copy.deepcopy(pr)
        raise AssertionError(path)

    def sync(self) -> Store:
        store = Store()
        queue_issues.sync(REPO, self.entries, store, 99)
        return store

    def approve(self, number: int) -> Store:
        self.comment(number, "@OvertureDB-bot approve")
        return self.sync()


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> GitHub:
    return GitHub(monkeypatch)


def test_sequential_issues_and_main_refresh_need_no_reapproval(remote: GitHub) -> None:
    remote.add_issue(1)
    remote.add_issue(2, tmdb_id=2)
    remote.sync()
    remote.approve(1)
    store = remote.approve(2)
    queue_prs.tick(REPO, store, 99)
    assert len(remote.prs) == 1
    first = store.next()
    assert first
    original_digest = first["record"]["digest"]
    head = first["attempt"]["head"]
    remote.base = "b" * 40  # Maintainer/Renovate merged while checks were pending.
    remote.entries[0]["year"] = 2025
    queue_prs.tick(REPO, store, 99)
    assert first["attempt"]["head"] != head
    assert first["record"]["digest"] == original_digest
    assert len(remote.prs) == 1
    remote.check = "success"
    queue_prs.tick(REPO, store, 99)
    assert remote.entries[0]["year"] == 2025
    assert remote.issues[1]["state"] == "closed"
    queue_prs.tick(REPO, store, 99)
    assert len(remote.prs) == 2
    assert all(r["status"] == "merged" for r in store.state["requests"])
    assert remote.issues[2]["state"] == "closed"
    queue_prs.tick(REPO, store, 99)
    assert len(remote.comments[1]) == 2  # One status comment and one approval.


def test_failed_checks_park_close_and_retry_without_approval(remote: GitHub) -> None:
    remote.add_issue(1)
    remote.add_issue(2, tmdb_id=2)
    remote.sync()
    remote.approve(1)
    store = remote.approve(2)
    remote.check = "failure"
    queue_prs.tick(REPO, store, 99)
    assert store.state["requests"][0]["status"] == "needs attention"
    assert remote.prs[100]["state"] == "closed"
    remote.check = "success"
    queue_prs.tick(REPO, store, 99)
    remote.comment(1, "@OvertureDB-bot retry")
    store = remote.sync()
    queue_prs.tick(REPO, store, 99)
    assert store.state["requests"][0]["status"] == "merged"
    assert len(remote.prs) == 3


def test_conflict_creates_new_preview_and_requires_new_command(remote: GitHub) -> None:
    remote.add_issue(1)
    remote.sync()
    store = remote.approve(1)
    remote.entries[0]["title"] = "Third value"
    queue_prs.tick(REPO, store, 99)
    assert store.state["requests"][0]["reapprove"]
    store = remote.sync()
    assert store.state["issues"]["1"]["status"] == "awaiting approval"
    queue_prs.tick(REPO, store, 99)
    assert not remote.prs
    remote.check = "success"
    store = remote.approve(1)
    queue_prs.tick(REPO, store, 99)
    assert remote.issues[1]["state"] == "closed"


@pytest.mark.parametrize("alteration", ["edit", "close", "reject", "revoke", "kind"])
def test_authorization_changes_stop_active_requests(
    remote: GitHub, alteration: str
) -> None:
    remote.add_issue(1)
    remote.sync()
    store = remote.approve(1)
    queue_prs.tick(REPO, store, 99)
    if alteration == "edit":
        remote.edited = remote.time()
    elif alteration == "close":
        remote.issues[1]["state"] = "closed"
    elif alteration == "reject":
        remote.comment(1, "@OvertureDB-bot reject wrong")
    elif alteration == "revoke":
        remote.permission = "read"
    else:
        remote.issues[1]["labels"] = []
    store = remote.sync()
    remote.check = "success"
    queue_prs.tick(REPO, store, 99)
    assert not remote.prs[100]["merged"]
    assert remote.prs[100]["state"] == "closed"


def test_status_labels_do_not_invalidate_and_historical_approvals_are_ignored(
    remote: GitHub,
) -> None:
    remote.add_issue(1)
    remote.comment(1, "@OvertureDB-bot approve")
    store = remote.sync()
    assert not store.state["requests"]
    store = remote.approve(1)
    remote.issues[1]["labels"].append({"name": "edit"})
    remote.events = [{"event": "labeled", "id": 200, "label": {"name": "edit"}}]
    store = remote.sync()
    assert len(store.state["requests"]) == 1
    remote.check = "success"
    queue_prs.tick(REPO, store, 99)
    assert remote.prs[100]["merged"]


def test_all_satisfied_completes_without_pr(remote: GitHub) -> None:
    remote.add_issue(1)
    remote.sync()
    store = remote.approve(1)
    remote.entries[0].update(title="Changed", youtube_id_overturedb="AB96CvvLZKc")
    queue_prs.tick(REPO, store, 99)
    assert not remote.prs
    assert remote.issues[1]["state"] == "closed"


def test_import_dedup_and_supersession_do_not_change_active_revision(
    remote: GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        queue_git, "import_snapshot", MagicMock(side_effect=imported_entries)
    )
    store = Store()
    first = store.enqueue("import", {"upstream": "1" * 40})
    assert store.enqueue("import", {"upstream": "1" * 40}) is first
    queue_prs.tick(REPO, store, 99)
    waiting = store.enqueue("import", {"upstream": "2" * 40})
    store.enqueue("import", {"upstream": "3" * 40})
    assert waiting["status"] == "superseded"
    assert first["record"]["upstream"] == "1" * 40
    remote.check = "success"
    queue_prs.tick(REPO, store, 99)
    queue_prs.tick(REPO, store, 99)
    assert store.state["requests"][-1]["status"] == "already satisfied"


def test_crash_after_pr_creation_recovers_same_pr(
    remote: GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote.add_issue(1)
    remote.sync()
    store = remote.approve(1)
    real_api = remote.api

    def crashing_api(
        path: str, payload: dict[str, Any] | None = None, *, method: str | None = None
    ) -> Any:
        result = real_api(path, payload, method=method)
        if path.endswith("/pulls"):
            raise RuntimeError("runner died after GitHub created PR")
        return result

    monkeypatch.setattr(github, "api", crashing_api)
    with pytest.raises(RuntimeError):
        queue_prs.tick(REPO, store, 99)
    monkeypatch.setattr(github, "api", remote.api)
    store = Store()
    remote.check = "success"
    queue_prs.tick(REPO, store, 99)
    assert len(remote.prs) == 1
    assert store.state["requests"][0]["status"] == "merged"


def test_crash_after_merge_and_duplicate_wakes_are_idempotent(
    remote: GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote.add_issue(1)
    remote.sync()
    store = remote.approve(1)
    queue_prs.tick(REPO, store, 99)
    remote.check = "success"
    real_save = store.save

    def crash() -> None:
        if store.state["requests"][0]["status"] == "merged":
            raise RuntimeError("crash after merge")
        real_save()

    monkeypatch.setattr(store, "save", crash)
    with pytest.raises(RuntimeError):
        queue_prs.tick(REPO, store, 99)
    store = Store()
    queue_prs.tick(REPO, store, 99)
    queue_prs.tick(REPO, store, 99)
    assert len(remote.prs) == 1
    assert remote.issues[1]["state"] == "closed"


@pytest.mark.parametrize("attack", ["head", "owner", "base", "diff", "native"])
def test_forged_or_changed_prs_never_merge(remote: GitHub, attack: str) -> None:
    remote.add_issue(1)
    remote.sync()
    store = remote.approve(1)
    queue_prs.tick(REPO, store, 99)
    pr = remote.prs[100]
    if attack == "head":
        pr["head"]["sha"] = "evil"
    elif attack == "owner":
        pr["user"]["id"] = 10
    elif attack == "base":
        pr["base"]["ref"] = "other"
    elif attack == "diff":
        pr["changed_files"] += 1
    else:
        pr["auto_merge"] = {"enabled_by": "someone"}
    remote.check = "success"
    queue_prs.tick(REPO, store, 99)
    assert not pr["merged"]
    assert store.state["requests"][0]["status"] == "needs attention"


def test_store_versions_concurrent_writes_and_multiple_active_are_rejected(
    remote: GitHub,
) -> None:
    left, right = Store(), Store()
    left.enqueue("import", {"upstream": "1" * 40})
    with pytest.raises(RuntimeError, match="CAS"):
        right.enqueue("import", {"upstream": "2" * 40})
    left.state["requests"][0]["status"] = "checking"
    left.enqueue("import", {"upstream": "3" * 40})["status"] = "checking"
    with pytest.raises(ValueError, match="More than one"):
        left.next()
    remote.state["version"] = 99
    with pytest.raises(ValueError, match="version"):
        Store()


def test_bulk_freezes_once_and_rejects_entire_invalid_archive(
    remote: GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote.add_issue(1)
    remote.issues[1]["labels"] = [{"name": "bulk"}]
    download = MagicMock(side_effect=archive_writer(movie(tmdb_id=2)))
    monkeypatch.setattr(automation, "download_archive", download)
    remote.sync()
    store = remote.approve(1)
    remote.check = "success"
    queue_prs.tick(REPO, store, 99)
    assert download.call_count == 1
    remote.add_issue(2)
    remote.issues[2]["labels"] = [{"name": "bulk"}]
    download.side_effect = archive_writer(movie(tmdb_id=3), movie(year=False))
    store = remote.sync()
    assert store.state["issues"]["2"]["status"] == "needs attention"


def test_guard_requires_verified_queue_not_bot_name(
    remote: GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setattr(guard, "api", remote.api)
    monkeypatch.setattr(guard, "load_state", remote.load)
    remote.add_issue(1)
    remote.sync()
    store = remote.approve(1)
    queue_prs.tick(REPO, store, 99)
    pr = copy.deepcopy(remote.prs[100])
    pr["user"]["login"] = github.BOT_LOGIN
    pr["author_association"] = "NONE"
    guard.validate_changes(pr, ["data/movies/tmdb-1.json"])
    remote.state["requests"] = []
    with pytest.raises(ValueError, match="maintainers"):
        guard.validate_changes(pr, ["data/movies/tmdb-1.json"])


def test_publication_disabled_by_default_and_main_only(
    remote: GitHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("QUEUE_BOT_ID", "99")
    monkeypatch.setenv("QUEUE_APP_ID", "42")
    monkeypatch.setenv("QUEUE_APP_SLUG", "overturedb")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/evil")
    with pytest.raises(ValueError, match="trusted"):
        contribution_queue.main()
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("QUEUE_IMPORT", "true")
    contribution_queue.main()
    assert remote.state["requests"][0]["status"] == "queued"
    assert not remote.prs
    monkeypatch.setenv("QUEUE_PUBLISH", "true")
    monkeypatch.setattr(queue_prs, "protections", MagicMock())
    monkeypatch.setattr(
        queue_git, "import_snapshot", MagicMock(side_effect=unchanged_entries)
    )
    contribution_queue.main()
    assert remote.state["requests"][0]["status"] == "already satisfied"
