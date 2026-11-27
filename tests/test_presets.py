"""Presets: their contract, repository checks, publication and contributions."""

lazy import base64
lazy import copy
lazy import io
lazy import json
lazy import shutil
lazy from pathlib import Path
lazy from typing import Any, cast
lazy from unittest.mock import MagicMock, patch

lazy import pytest
lazy import yaml
lazy from PIL import Image

lazy from schema.contract import (
    PRESET_ISSUE_FORM,
    PRESET_ISSUE_FORM_FIELDS,
    PRESET_SCHEMA,
    art_source,
    canonical_art_url,
    catalog_art_url,
    preset_image_path,
    preset_image_url,
    preset_requires,
    read_presets,
    validate_preset,
)
lazy from scripts import catalog, github, publication
lazy from scripts.automation import evaluate_issue
lazy from scripts.contribution import NoChangesError
lazy from scripts.preset_contribution import (
    CATEGORIES,
    HEADINGS,
    process_preset,
    reencode,
    slug,
)

ROOT = Path(__file__).resolve().parents[1]
POSTER = "https://autogitr.github.io/OvertureDB/presets/holidays/christmas-poster.jpg"
TMDB = "https://image.tmdb.org/t/p/original/zgZRJZvZn5cpsWAB0zMUdad3iZd.jpg"
ATTACHMENT = (
    "https://github.com/user-attachments/assets/0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
)


def image(width: int, height: int, kind: str = "JPEG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(output, kind)
    return output.getvalue()


def preset(**changes: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "preset_version": 1,
        "preset": {
            "id": "holidays",
            "title": "Holidays",
            "description": "Holiday titles.",
            "category": "seasonal",
            "tags": [],
            "media_types": ["movie", "show"],
        },
        "groups": [
            {
                "name": "Decades",
                "generator": {"dimension": "decade", "media_types": ["movie"]},
            }
        ],
        "collections": [
            {
                "title": "Christmas",
                "collection_group": "Holidays",
                "active_start_mmdd": "12-01",
                "active_end_mmdd": "12-26",
                "criteria": {
                    "movie": {
                        "conditions": [
                            {
                                "kind": "field",
                                "field": "tmdb_keyword",
                                "operator": "is",
                                "value": "christmas",
                            }
                        ]
                    },
                    "show": {
                        "conditions": [
                            {
                                "kind": "source",
                                "source": {"type": "mdblist", "identifiers": ["a/b"]},
                            }
                        ]
                    },
                },
            }
        ],
    }
    value.update(changes)
    return value


def test_every_preset_in_the_repository_is_published_as_given() -> None:
    files = catalog.preset_files(ROOT)
    assert files
    for path, value in files:
        assert path.stem == value["preset"]["id"]


def test_presets_name_what_they_need() -> None:
    assert preset_requires(preset()) == ["mdblist", "tmdb"]
    assert preset_requires(preset(collections=[])) == []
    franchises = preset(
        groups=[
            {
                "name": "Franchises",
                "generator": {"dimension": "franchise", "media_types": ["movie"]},
            }
        ],
        collections=[],
    )
    assert preset_requires(franchises) == ["tmdb"]


def test_overturedb_art_is_preset_art_only(subtests: pytest.Subtests) -> None:
    assert art_source(POSTER) == "overturedb"
    assert canonical_art_url(POSTER) == POSTER
    assert preset_image_url("holidays", "christmas-poster.jpg") == POSTER
    assert preset_image_path(POSTER) == "data/presets/holidays/christmas-poster.jpg"
    assert preset_image_path(TMDB) is None
    with pytest.raises(ValueError, match="must come from"):
        catalog_art_url(POSTER)
    for link in (
        "https://autogitr.github.io/Overture/docs/logo.png",
        "https://autogitr.github.io/OvertureDB/presets/Holidays/poster.jpg",
        "https://autogitr.github.io/OvertureDB/presets/holidays/poster.gif",
    ):
        with subtests.test(link=link), pytest.raises(ValueError, match="OvertureDB"):
            canonical_art_url(link)


def _with(value: dict[str, Any], path: str, item: Any) -> dict[str, Any]:
    value = copy.deepcopy(value)
    *parents, last = path.split(".")
    target: Any = value
    for part in parents:
        target = cast(
            "Any", target[int(part)] if isinstance(target, list) else target[part]
        )
    if isinstance(target, list):
        target[int(last)] = item
    else:
        target[last] = item
    return value


def test_a_preset_is_refused_for_what_overture_could_not_add(
    subtests: pytest.Subtests,
) -> None:
    condition = "collections.0.criteria.movie.conditions.0"
    cases: dict[str, dict[str, Any]] = {
        "add a collection or a set": _with(preset(), "collections", [])
        | {"groups": []},
        "give each its own title": _with(
            preset(), "collections", [preset()["collections"][0]] * 2
        ),
        "not valid under any": _with(preset(), f"{condition}.field", "rating"),
        "names something only one install has": _with(
            preset(), f"{condition}.field", "folder"
        ),
        "cannot use the gt operator": _with(preset(), f"{condition}.operator", "gt"),
        "cannot be tested on shows": _with(
            preset(),
            "collections.0.criteria.show.conditions.0",
            {"kind": "field", "field": "director", "operator": "is", "value": "x"},
        ),
        "cannot select shows": _with(
            preset(),
            "collections.0.criteria.show.conditions.0.source",
            {"type": "tmdb_collection", "collection_id": 10},
        ),
        "TMDB has no upcoming chart of shows": _with(
            preset(),
            "collections.0.criteria.show.conditions.0.source",
            {"type": "tmdb_chart", "chart": "upcoming"},
        ),
        "network sets cannot hold movies": _with(
            preset(), "groups.0.generator.dimension", "network"
        ),
    }
    for message, value in cases.items():
        with subtests.test(message), pytest.raises(ValueError, match=message):
            validate_preset(value, published=False)


def test_a_published_preset_describes_itself_and_links_preset_art(
    subtests: pytest.Subtests,
) -> None:
    validate_preset(preset(), published=True)
    validate_preset(preset(preset=None) | {"preset": None}, published=False)
    art = "collections.0.art"
    cases = {
        "describe the preset": {k: v for k, v in preset().items() if k != "preset"},
        "add show": _with(preset(), "preset.media_types", ["movie"]),
        "artwork must come from": _with(
            preset(), art, {"poster": {"url": "https://example.com/poster.jpg"}}
        ),
        "canonical form": _with(
            preset(),
            art,
            {"poster": {"url": TMDB.replace("original", "w342")}},
        ),
        "link the preset's own images": _with(
            preset(), art, {"poster": {"url": POSTER.replace("holidays", "other")}}
        ),
    }
    # What a collection requests, labels or shows, and its art and themes, are
    # the adding install's own, so a preset has no place for them.
    for key in ("request_missing", "auto_art", "visible_home", "separator"):
        with subtests.test(key), pytest.raises(ValueError, match="not allowed"):
            validate_preset(_with(preset(), f"groups.0.{key}", True), published=False)
    for message, value in cases.items():
        with subtests.test(message), pytest.raises(ValueError, match=message):
            validate_preset(value, published=True)


def test_the_bundle_keeps_each_preset_for_its_reader_to_check() -> None:
    header = {"generated_at": "2026-09-04T12:00:00Z", "source_revision": "a" * 40}
    data = catalog.dump_presets(header, [preset(), {"unknown": True}])
    assert read_presets(data) == (header, [preset(), {"unknown": True}])
    for bundle, message in (
        (b"[]", "not an OvertureDB presets bundle"),
        (b'{"preset_version": 2}', "Unsupported"),
        (b'{"preset_version": 1, "presets": {}}', "no presets list"),
        (b'{"preset_version": 1, "presets": []}', "header is incomplete"),
    ):
        with pytest.raises(ValueError, match=message):
            read_presets(bundle)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A checkout holding the schema, the notices and one preset with a poster."""
    (tmp_path / "data/movies").mkdir(parents=True)
    (tmp_path / "data/presets/holidays").mkdir(parents=True)
    (tmp_path / "licenses").mkdir()
    (tmp_path / "licenses/THIRD_PARTY_NOTICES.md").write_text("Notices\n")
    shutil.copytree(catalog.ROOT / "schema", tmp_path / "schema")
    value = _with(preset(), "collections.0.art", {"poster": {"url": POSTER}})
    (tmp_path / "data/presets/holidays.json").write_text(json.dumps(value))
    (tmp_path / "data/presets/holidays/christmas-poster.jpg").write_bytes(
        image(1000, 1500)
    )
    return tmp_path


def test_presets_are_published_with_their_images_and_schemas(root: Path) -> None:
    catalog.build(
        root / "public",
        root=root,
        revision="a" * 40,
        generated_at="2026-09-04T12:00:00Z",
    )
    public = root / "public"
    header, presets = read_presets((public / "presets.json").read_bytes())
    assert header["source_revision"] == "a" * 40
    assert [validate_preset(value, published=True) for value in presets] == [
        json.loads((root / "data/presets/holidays.json").read_text())
    ]
    assert (public / "presets/holidays/christmas-poster.jpg").read_bytes() == (
        root / "data/presets/holidays/christmas-poster.jpg"
    ).read_bytes()
    for name in ("presets.json", "schema/preset.schema.json"):
        assert name in (public / "index.html").read_text()
    assert "presets.json" in (public / "SHA256SUMS").read_text()
    assert (public / "schema/preset-vocabulary.json").is_file()


def test_entries_and_presets_are_found_apart(root: Path) -> None:
    assert catalog.entry_files(root) == []
    assert [path.name for path, _ in catalog.preset_files(root)] == ["holidays.json"]


def test_preset_folders_hold_exactly_the_images_their_presets_link(
    subtests: pytest.Subtests, root: Path
) -> None:
    folder = root / "data/presets/holidays"
    poster = folder / "christmas-poster.jpg"
    cases = {
        "No preset links": lambda: (folder / "extra.jpg").write_bytes(b""),
        "Preset image is missing": poster.unlink,
        "is not a JPG image": lambda: poster.write_bytes(image(1000, 1500, "PNG")),
        "outside 1% of": lambda: poster.write_bytes(image(1000, 1000)),
        "below the recommended": lambda: poster.write_bytes(image(500, 750)),
        "sit directly in": lambda: (folder / "nested.json").write_text("{}"),
        "must be data/presets/holidays.json": lambda: (
            root / "data/presets/holidays.json"
        ).rename(root / "data/presets/other.json"),
    }
    original = poster.read_bytes()
    for message, change in cases.items():
        with subtests.test(message):
            change()
            with pytest.raises(ValueError, match=message):
                catalog.preset_files(root)
            for path in (folder / "extra.jpg", folder / "nested.json"):
                path.unlink(missing_ok=True)
            if (moved := root / "data/presets/other.json").exists():
                moved.rename(root / "data/presets/holidays.json")
            poster.write_bytes(original)


def test_preset_images_must_be_regular_files(root: Path) -> None:
    (root / "data/presets/link.json").symlink_to(root / "data/presets/holidays.json")
    with pytest.raises(ValueError, match="regular local file"):
        catalog.preset_files(root)


def test_a_missing_preset_folder_holds_no_presets(tmp_path: Path) -> None:
    assert catalog.preset_files(tmp_path) == []


def test_validate_checks_preset_provider_links(root: Path) -> None:
    value = _with(preset(), "collections.0.art", {"background": {"url": TMDB}})
    assert catalog.preset_provider_urls([value]) == {TMDB}
    assert catalog.preset_provider_urls([preset()]) == set()


def form(**fields: str) -> str:
    """An issue body as GitHub writes a filled preset form."""
    values = {
        "id": "_No response_",
        "title": "Holidays",
        "description": "Holiday titles.",
        "category": "seasonal",
        "tags": "christmas, halloween",
        "file": json.dumps({k: v for k, v in preset().items() if k != "preset"}),
        "images": "_No response_",
        "licence": "- [ ] I made the images",
        "reason": "_No response_",
        "remove": "- [ ] Remove this preset",
    } | fields
    return "\n\n".join(
        f"### {HEADINGS[key]}\n\n{value}" for key, value in values.items()
    )


def no_download(url: str, limit: int) -> bytes:
    raise AssertionError(f"Downloaded {url} ({limit} bytes)")


def test_a_preset_form_becomes_its_file(tmp_path: Path) -> None:
    result = process_preset(form(), tmp_path, no_download)
    path = "data/presets/holidays.json"
    assert result.preset["preset"] == preset()["preset"] | {
        "tags": ["christmas", "halloween"]
    }
    assert json.loads(result.additions[path]) == result.preset
    assert not result.is_modification
    assert result.deletions == []
    (tmp_path / path).parent.mkdir(parents=True)
    (tmp_path / path).write_text(str(result.additions[path]))
    with pytest.raises(ValueError, match="To change it, give its ID"):
        process_preset(form(), tmp_path, no_download)
    with pytest.raises(NoChangesError, match="already holds the Holidays preset"):
        process_preset(form(id="holidays", reason="Same"), tmp_path, no_download)


def test_a_preset_file_may_be_fenced_or_attached(tmp_path: Path) -> None:
    text = json.dumps(preset(preset=None))
    fenced = process_preset(form(file=f"```json\n{text}\n```"), tmp_path, no_download)
    attached = process_preset(
        form(file=f"[holidays.json]({ATTACHMENT})"),
        tmp_path,
        lambda url, limit: text.encode() if url == ATTACHMENT else b"",
    )
    assert fenced.preset == attached.preset


def test_preset_forms_are_refused_for_what_they_lack(
    subtests: pytest.Subtests, tmp_path: Path
) -> None:
    cases = {
        "exactly one preset file": form(file="see above"),
        "not JSON": form(file="{oops"),
        "not an export": form(file="[]"),
        "title and a description": form(description="_No response_"),
        "Choose one of the categories": form(category="music"),
        "letters and numbers": form(title="!!!"),
        "one image per line": form(images="Christmas poster"),
        "no collection titled Easter": form(images=f"Easter poster: {TMDB}"),
        "Link collections.0.art.poster.url to TMDB": form(
            images="Christmas poster: https://example.com/a.jpg"
        ),
        "Attach the image": form(images=f"Christmas poster: {POSTER}"),
    }
    for message, body in cases.items():
        with subtests.test(message), pytest.raises(ValueError, match=message):
            process_preset(body, tmp_path, no_download)


def test_attached_images_are_reencoded_into_the_preset_folder(tmp_path: Path) -> None:
    exif = Image.Exif()
    exif[0x010E] = "secret"
    output = io.BytesIO()
    Image.new("RGB", (1000, 1500), "red").save(output, "JPEG", exif=exif)
    lines = (
        f"- Christmas poster: ![poster]({ATTACHMENT})\n\nChristmas background: {TMDB}"
    )
    body = form(images=lines)

    def download(url: str, limit: int) -> bytes:
        assert url == ATTACHMENT
        return output.getvalue()

    with pytest.raises(ValueError, match="Confirm you made the attached images"):
        process_preset(body, tmp_path, download)
    result = process_preset(
        body.replace("- [ ] I made", "- [X] I made"), tmp_path, download
    )
    stored = result.additions["data/presets/holidays/christmas-poster.jpg"]
    assert isinstance(stored, bytes)
    with Image.open(io.BytesIO(stored)) as saved:
        assert saved.size == (1000, 1500)
        assert not saved.getexif()
    assert result.preset["collections"][0]["art"] == {
        "poster": {"url": POSTER},
        "background": {"url": TMDB},
    }
    assert result.attached == {POSTER: ATTACHMENT}


def test_a_changed_preset_drops_the_images_it_no_longer_links(root: Path) -> None:
    result = process_preset(
        form(id="holidays", title="Festive", reason="New poster"), root, no_download
    )
    assert result.is_modification
    assert result.reason == "New poster"
    assert result.preset["preset"]["id"] == "holidays"
    assert result.preset["preset"]["title"] == "Festive"
    assert result.deletions == ["data/presets/holidays/christmas-poster.jpg"]


def test_a_published_preset_is_changed_or_removed_by_its_id_with_a_reason(
    subtests: pytest.Subtests, root: Path
) -> None:
    cases = {
        "needs a reason": form(id="holidays"),
        "No published preset has the ID easter": form(id="easter", reason="Gone"),
        "Give the ID of the published preset to remove": form(
            title="Easter", remove="- [X] Remove this preset"
        ),
    }
    for message, body in cases.items():
        with subtests.test(message), pytest.raises(ValueError, match=message):
            process_preset(body, root, no_download)
    removed = process_preset(
        form(id="Holidays", reason="Duplicated", remove="- [X] Remove", file=""),
        root,
        no_download,
    )
    assert removed.removed
    assert removed.additions == {}
    assert removed.deletions == [
        "data/presets/holidays.json",
        "data/presets/holidays/christmas-poster.jpg",
    ]
    assert removed.preset["preset"]["id"] == "holidays"


@patch("scripts.automation.check_art_url")
def test_a_removal_previews_what_leaves(check: MagicMock, root: Path) -> None:
    issue = {
        "number": 8,
        "title": "[Preset]: Holidays",
        "body": form(id="holidays", reason="Duplicated", remove="- [x] Remove"),
        "state": "open",
        "labels": [{"name": "preset"}],
    }
    plan = evaluate_issue("AutoGitr/OvertureDB", issue, root)
    assert plan.headline == "Remove preset: Holidays (#8)"
    assert plan.is_modification
    assert "**Reason:** Duplicated" in plan.preview_body
    assert "`data/presets/holidays/christmas-poster.jpg`" in plan.preview_body
    assert "```json" not in plan.preview_body
    check.assert_not_called()


def test_only_well_shaped_jpeg_and_png_images_are_kept(
    subtests: pytest.Subtests,
) -> None:
    data, extension = reencode(image(1000, 1500, "PNG"), "poster")
    assert extension == "png"
    assert data.startswith(b"\x89PNG")
    for message, data in {
        "JPEG or PNG": image(1000, 1500, "GIF"),
        "could not be read": b"not an image",
        "outside 1% of": image(1280, 1280),
    }.items():
        with subtests.test(message), pytest.raises(ValueError, match=message):
            reencode(data, "background")


def test_slugs_are_lowercase_words() -> None:
    assert slug("Valentine's Day!") == "valentine-s-day"


@patch("scripts.automation.check_art_url", return_value=(1280, 720))
def test_a_preset_issue_previews_what_it_adds(check: MagicMock, tmp_path: Path) -> None:
    body = form(images=f"Christmas background: {TMDB}")
    issue = {
        "number": 7,
        "title": "[Preset]: Holidays",
        "body": body,
        "state": "open",
        "labels": [{"name": "preset"}],
    }
    plan = evaluate_issue("AutoGitr/OvertureDB", issue, tmp_path)
    assert plan.headline == "Add preset: Holidays (#7)"
    assert "| **Decades** | Set by decade | movie |" in plan.preview_body
    assert "| Christmas | Collection in Holidays | movie, show |" in plan.preview_body
    assert "**Needs:** mdblist, tmdb" in plan.preview_body
    assert f"![collections.0.art.background.url]({TMDB})" in plan.preview_body
    check.assert_called_once_with(TMDB)
    again = evaluate_issue("AutoGitr/OvertureDB", issue, tmp_path)
    assert plan.fingerprint == again.fingerprint
    check.return_value = (1000, 1000)
    with pytest.raises(ValueError, match="outside 1% of"):
        evaluate_issue("AutoGitr/OvertureDB", issue, tmp_path)


def test_bot_commits_carry_preset_files_and_images() -> None:
    for path in (
        "data/presets/holidays.json",
        "data/presets/holidays/christmas-poster.jpg",
        "data/presets/holidays/christmas-background.png",
    ):
        github.validate_bot_path(path)
    for path in (
        "data/presets/Holidays.json",
        "data/presets/holidays/poster.gif",
        "data/presets/holidays/nested/poster.jpg",
    ):
        with pytest.raises(ValueError, match="only modify catalog entries"):
            github.validate_bot_path(path)


@patch("scripts.github.api")
def test_binary_additions_are_committed_as_they_are(api: MagicMock) -> None:
    api.return_value = {"data": {"createCommitOnBranch": {"commit": {"oid": "c"}}}}
    github.commit_files(
        "o/r",
        "main",
        "b",
        "Add preset",
        "",
        {"data/presets/a/b.jpg": b"\xff\xd8\xff", "data/presets/a.json": "{}"},
        [],
    )
    additions = api.call_args.args[1]["variables"]["input"]["fileChanges"]["additions"]
    assert [base64.b64decode(item["contents"]) for item in additions] == [
        b"{}",
        b"\xff\xd8\xff",
    ]


@patch("scripts.github.run")
def test_candidates_write_images_as_bytes(run: MagicMock, tmp_path: Path) -> None:
    run.return_value = ""
    publication.validate_candidate(
        tmp_path, {"data/presets/a/b.jpg": b"\xff\xd8\xff"}, []
    )
    assert (tmp_path / "data/presets/a/b.jpg").read_bytes() == b"\xff\xd8\xff"


def test_the_preset_form_has_the_fields_the_contract_names() -> None:
    form = yaml.safe_load(
        (ROOT / ".github/ISSUE_TEMPLATE" / PRESET_ISSUE_FORM).read_text()
    )
    fields = {field["id"]: field for field in form["body"] if "id" in field}
    assert set(PRESET_ISSUE_FORM_FIELDS.values()) <= set(fields)
    for name, field_id in PRESET_ISSUE_FORM_FIELDS.items():
        assert fields[field_id]["attributes"]["label"] == HEADINGS[name]
    assert tuple(fields["category"]["attributes"]["options"]) == CATEGORIES
    assert tuple(PRESET_SCHEMA["$defs"]["PresetCategory"]["enum"]) == CATEGORIES
    assert form["labels"] == ["preset"]
