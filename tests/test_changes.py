"""Reviewed effects survive unrelated main changes and conflict atomically."""

lazy import copy
lazy import json

lazy import pytest

lazy from scripts.changes import ConflictError, between, change, file_changes, reconcile
lazy from tests.test_catalog import movie


def test_field_reconciliation_and_partial_satisfaction() -> None:
    before = movie()
    after = movie(title="New title", year=2025)
    operations = json.loads(json.dumps([change(before, after)]))
    live = movie(
        title="New title", background_url="https://image.tmdb.org/t/p/original/bg.jpg"
    )
    result = reconcile([live, movie(tmdb_id=2)], operations)
    assert result[0] == {**live, "year": 2025}
    assert result[1] == movie(tmdb_id=2)
    assert reconcile(result, operations) == result
    assert before == movie()


def test_seasons_use_numbers_and_preserve_other_seasons() -> None:
    before = {
        **movie(media_type="show"),
        "seasons": [
            {
                "season_num": 1,
                "poster_url": "https://image.tmdb.org/t/p/original/a.jpg",
            },
        ],
    }
    after = copy.deepcopy(before)
    after["seasons"][0]["poster_url"] = "https://image.tmdb.org/t/p/original/b.jpg"
    current = copy.deepcopy(before)
    current["seasons"].insert(
        0, {"season_num": 0, "poster_url": "https://image.tmdb.org/t/p/original/c.jpg"}
    )
    result = reconcile([current], [change(before, after)])[0]
    assert result["seasons"][0] == current["seasons"][0]
    assert result["seasons"][1] == after["seasons"][0]
    assert reconcile([after], [change(after, before)])[0] == before
    assert (
        reconcile([after], [change(after, {**before, "seasons": []})])[0]["seasons"]
        == []
    )


@pytest.mark.parametrize(
    "current,before,after",
    [
        ([movie(title="Third")], movie(), movie(title="Intended")),
        ([movie(imdb_id="tt2")], movie(imdb_id="tt1"), movie(imdb_id="tt1", year=2025)),
        ([], movie(), movie(year=2025)),
        ([movie(year=2025)], None, movie()),
        ([movie(year=2025)], movie(), None),
        ([movie(), movie(tmdb_id=2, imdb_id="tt2")], movie(), movie(imdb_id="tt2")),
    ],
)
def test_conflicts_never_apply_a_bulk_subset(
    current: list[dict[str, object]],
    before: dict[str, object] | None,
    after: dict[str, object] | None,
) -> None:
    original = copy.deepcopy(current)
    with pytest.raises(ConflictError):
        reconcile(current, [change(None, movie(tmdb_id=9)), change(before, after)])
    assert current == original


def test_creations_deletions_identity_additions_and_tampering() -> None:
    entry = movie()
    assert reconcile([], [change(None, entry)]) == [entry]
    assert reconcile([entry], [change(None, entry)]) == [entry]
    assert reconcile([], [change(entry, None)]) == []
    assert reconcile([entry], [change(entry, None)]) == []
    enriched = movie(imdb_id="tt1")
    assert reconcile([entry], [change(entry, enriched)]) == [enriched]
    assert reconcile([enriched], [change(entry, enriched)]) == [enriched]
    invalid = change(entry, enriched)
    invalid["fields"] = {}
    with pytest.raises(ConflictError, match="canonical"):
        reconcile([entry], [invalid])
    assert between([entry], [enriched, movie(tmdb_id=2)]) == [
        change(entry, enriched),
        change(None, movie(tmdb_id=2)),
    ]
    assert between([entry], []) == [change(entry, None)]
    assert between([entry], [entry]) == []
    with pytest.raises(ConflictError, match="Ambiguous"):
        between([enriched], [entry, movie(tmdb_id=2, imdb_id="tt1")])
    assert file_changes([entry], []) == {"data/movies/tmdb-1.json": None}
