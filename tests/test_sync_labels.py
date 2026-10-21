"""Label reconciliation must make drift visible before changing anything."""

lazy import json
lazy from unittest.mock import MagicMock, patch

lazy import pytest

lazy from scripts import github, sync_labels

LABEL: sync_labels.Label = {
    "name": "ci",
    "color": "ededed",
    "description": "Automation",
}


@patch.object(github, "gh")
def test_empty_reply_is_none_and_method_is_passed(gh: MagicMock) -> None:
    gh.return_value = ""
    assert github.api("endpoint", method="DELETE") is None
    gh.assert_called_once_with("api", "endpoint", "--method", "DELETE", payload=None)


@patch.object(github, "gh")
def test_pagination_preserves_every_page(gh: MagicMock) -> None:
    gh.return_value = json.dumps([[{"number": 1}], [{"number": 2}]])
    assert github.pages("endpoint") == [{"number": 1}, {"number": 2}]
    gh.assert_called_once_with("api", "endpoint", "--paginate", "--slurp")


@patch.object(sync_labels, "api")
@patch.object(sync_labels, "pages", return_value=[])
def test_preview_never_writes(_pages: MagicMock, api: MagicMock) -> None:
    assert sync_labels.sync("owner/repo", [LABEL], apply=False)
    api.assert_not_called()


@patch.object(sync_labels, "api")
@patch.object(
    sync_labels,
    "pages",
    return_value=[
        {"name": "ci", "color": "ededed", "description": "Automation"},
        {"name": "unmanaged"},
    ],
)
def test_unknown_labels_are_previewed_and_deleted_on_apply(
    _pages: MagicMock, api: MagicMock
) -> None:
    assert sync_labels.sync("owner/repo", [LABEL], apply=False)
    api.assert_not_called()
    assert sync_labels.sync("owner/repo", [LABEL], apply=True)
    api.assert_called_once_with("repos/owner/repo/labels/unmanaged", method="DELETE")


@patch.object(sync_labels, "api")
@patch.object(sync_labels, "pages")
def test_create_update_and_idempotence(pages: MagicMock, api: MagicMock) -> None:
    pages.return_value = []
    assert sync_labels.sync("owner/repo", [LABEL], apply=True)
    assert api.call_args_list[-1].kwargs["method"] == "POST"
    pages.return_value = [{**dict(LABEL), "description": "Outdated"}]
    assert sync_labels.sync("owner/repo", [LABEL], apply=True)
    assert api.call_args_list[-1].kwargs["method"] == "PATCH"
    api.reset_mock()
    pages.return_value = [dict(LABEL)]
    assert not sync_labels.sync("owner/repo", [LABEL], apply=True)
    api.assert_not_called()


@patch.object(sync_labels, "sync", return_value=True)
def test_check_fails_on_drift_without_writing(sync: MagicMock) -> None:
    with patch("sys.argv", ["sync_labels.py", "--check"]):
        assert sync_labels.main() == 1
    assert not sync.call_args_list[-1].kwargs["apply"]
    sync.return_value = False
    with patch("sys.argv", ["sync_labels.py", "--check"]):
        assert sync_labels.main() == 0


@patch.object(sync_labels, "pages")
def test_invalid_repository_never_reaches_github(pages: MagicMock) -> None:
    with pytest.raises(ValueError):
        sync_labels.sync("owner/repo?query", [LABEL], apply=True)
    pages.assert_not_called()
