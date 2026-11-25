"""Turn a preset issue form into the preset file and images it adds."""

lazy import io
lazy import json
lazy import re
lazy from collections.abc import Callable
lazy from dataclasses import dataclass, field
lazy from pathlib import Path
lazy from typing import Any, cast

lazy from PIL import Image

lazy from schema.contract import (
    PRESET_DIR,
    PRESET_ID_PATTERN,
    PRESET_SCHEMA,
    art_source,
    canonical_art_url,
    preset_art_urls,
    preset_image_path,
    preset_image_url,
    preset_repo_path,
    validate_preset,
)

lazy from .catalog import MAX_PRESET_IMAGE_BYTES, aspect_problem, resolution_warning
lazy from .contribution import NoChangesError, extract_field, reason_text, unwrap

#: The largest preset file an issue attaches.
MAX_PRESET_FILE_BYTES = 256 * 1024
#: More pixels than any poster or background needs, so a decompression bomb
#: is refused before it is decoded.
MAX_IMAGE_PIXELS = 40_000_000
#: The categories a preset may be filed under, as the issue form lists them.
CATEGORIES: tuple[str, ...] = tuple(PRESET_SCHEMA["$defs"]["PresetCategory"]["enum"])
_IMAGE_LINE = re.compile(
    r"(?P<title>.+?)\s+(?P<slot>poster|background)\s*:\s*(?P<link>.+)", re.IGNORECASE
)
_LINK = re.compile(r"https://[^\s)\"'<>]+")

#: Fetches a GitHub attachment, at most *limit* bytes of it.
type Download = Callable[[str, int], bytes]


@dataclass(slots=True)
class PresetContribution:
    """The files a preset issue adds and removes, and how to preview them."""

    preset: dict[str, Any]
    additions: dict[str, str | bytes] = field(default_factory=dict[str, str | bytes])
    deletions: list[str] = field(default_factory=list[str])
    is_modification: bool = False
    #: The preset and its images leave OvertureDB.
    removed: bool = False
    #: Why a published preset is changed or removed.
    reason: str | None = None
    #: Each image the issue attached, by the link the preset gives it.
    attached: dict[str, str] = field(default_factory=dict[str, str])


def slug(text: str) -> str:
    """Return *text* as lowercase words joined by hyphens: ``Christmas Eve``."""
    return "-".join(re.findall(r"[a-z0-9]+", text.casefold()))


#: The heading GitHub writes for each preset form field, by contract name.
HEADINGS: dict[str, str] = {
    "id": "Preset ID",
    "title": "Preset title",
    "description": "Description",
    "category": "Category",
    "tags": "Tags",
    "file": "Preset file",
    "images": "Images",
    "licence": "Licence",
    "reason": "Reason for modification",
    "remove": "Removal",
}


def _field(body: str, name: str) -> str | None:
    return extract_field(body, HEADINGS[name])


def _file(raw: str, download: Download) -> dict[str, Any]:
    text = raw.strip()
    if fence := re.fullmatch(r"(`{3,})[a-z]*\n(.*)\n\1", text, re.DOTALL):
        text = fence[2].strip()
    if not text.startswith("{"):
        links = _LINK.findall(text)
        if len(links) == 1:
            text = download(links[0], MAX_PRESET_FILE_BYTES).decode("utf-8")
        elif not text.startswith("["):
            raise ValueError(
                "Attach or paste exactly one preset file exported from Overture."
            )
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"The preset file is not JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("The preset file is not an export from Overture.")
    return cast("dict[str, Any]", value)


def _identifier(body: str, root: Path) -> tuple[str, bool]:
    """The preset's ID, and whether OvertureDB already holds it.

    A new preset's ID is made from its title; a published one is named by
    its ID, so its title can change without making a second preset.
    """
    given = unwrap(_field(body, "id"))
    identifier = (
        given.casefold() if given else slug(unwrap(_field(body, "title")) or "")
    )
    if not PRESET_ID_PATTERN.fullmatch(identifier) or len(identifier) > 60:
        raise ValueError("Give the preset a title of letters and numbers.")
    exists = (root / preset_repo_path(identifier)).is_file()
    if given and not exists:
        raise ValueError(
            f"No published preset has the ID {identifier}; leave Preset ID empty "
            "for a new preset."
        )
    if not given and exists:
        raise ValueError(
            f"A preset with the ID {identifier} exists. To change it, give its ID "
            "under Preset ID; for a new preset, choose another title."
        )
    return identifier, exists


def _metadata(body: str, identifier: str, preset: dict[str, Any]) -> dict[str, Any]:
    title = unwrap(_field(body, "title"))
    description = (_field(body, "description") or "").strip()
    category = (unwrap(_field(body, "category")) or "").casefold()
    if not title or not description:
        raise ValueError("Give the preset a title and a description.")
    if category not in CATEGORIES:
        raise ValueError(f"Choose one of the categories: {', '.join(CATEGORIES)}.")
    tags = [
        tag
        for raw in (unwrap(_field(body, "tags")) or "").split(",")
        if (tag := raw.strip())
    ]
    collections: list[dict[str, Any]] = preset.get("collections", [])
    groups: list[dict[str, Any]] = preset.get("groups", [])
    media_types: set[str] = {
        media_type
        for collection in collections
        for media_type in collection.get("criteria", {})
    }
    for group in groups:
        generator: dict[str, Any] = group.get("generator") or {}
        media_types.update(generator.get("media_types", []))
    return {
        "id": identifier,
        "title": title,
        "description": description,
        "category": category,
        "tags": tags,
        "media_types": sorted(media_types),
    }


def reencode(data: bytes, kind: str) -> tuple[bytes, str]:
    """Return an image decoded and saved anew, with its file extension.

    Saving afresh keeps only pixels: no metadata, comments or appended data.

    Raises:
        ValueError: When it is not a JPEG or PNG of *kind*'s shape and size.
    """
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("Attach images as JPEG or PNG.")
            image.load()
            if problem := aspect_problem(kind, *image.size) or resolution_warning(
                kind, *image.size
            ):
                raise ValueError(f"The {kind} is {problem}.")
            output = io.BytesIO()
            if image.format == "PNG":
                image.save(output, "PNG", optimize=True)
                extension = "png"
            else:
                image.convert("RGB").save(output, "JPEG", quality=92, optimize=True)
                extension = "jpg"
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"The {kind} could not be read as an image.") from exc
    if len(output.getvalue()) > MAX_PRESET_IMAGE_BYTES:
        raise ValueError(f"The {kind} is larger than 5 MB.")
    return output.getvalue(), extension


def _images(
    body: str, preset: dict[str, Any], download: Download
) -> tuple[dict[str, bytes], dict[str, str]]:
    """Give each collection the art the images field names, and return the files."""
    collections = {
        collection["title"].casefold(): collection
        for collection in preset.get("collections", [])
    }
    files: dict[str, bytes] = {}
    attached: dict[str, str] = {}
    for line in (_field(body, "images") or "").splitlines():
        if not line.strip():
            continue
        match = _IMAGE_LINE.fullmatch(line.strip().lstrip("-* ").strip())
        links = _LINK.findall(match["link"]) if match else []
        if match is None or len(links) != 1:
            raise ValueError(
                "Write one image per line, as `<collection title> poster: <link>`."
            )
        title = unwrap(match["title"].strip("`*_ ")) or ""
        collection = collections.get(title.casefold())
        if collection is None:
            raise ValueError(f"The preset has no collection titled {title}.")
        slot = match["slot"].casefold()
        link = links[0]
        if link.startswith("https://github.com/"):
            data, extension = reencode(download(link, MAX_PRESET_IMAGE_BYTES), slot)
            name = f"{slug(collection['title'])}-{slot}.{extension}"
            url = preset_image_url(preset["preset"]["id"], name)
            files[f"{PRESET_DIR}/{preset['preset']['id']}/{name}"] = data
            attached[url] = link
        else:
            url = canonical_art_url(link)
        art = collection.setdefault("art", {})
        art[slot] = {**art.get(slot, {}), "url": url}
    return files, attached


def _folder_files(root: Path, identifier: str) -> list[str]:
    folder = root / PRESET_DIR / identifier
    return sorted(
        image.relative_to(root).as_posix()
        for image in folder.glob("*")
        if image.is_file()
    )


def process_preset(body: str, root: Path, download: Download) -> PresetContribution:
    """Plan the files a preset issue adds, replaces and removes.

    Raises:
        NoChangesError: When the repository already holds the preset as given.
        ValueError: Naming what the issue needs to change.
    """
    identifier, exists = _identifier(body, root)
    reason = reason_text(_field(body, "reason")) or None
    if exists and reason is None:
        raise ValueError(
            "Changing or removing a published preset needs a reason: explain why "
            "under Reason for modification."
        )
    current = root / preset_repo_path(identifier)
    if "[x]" in (_field(body, "remove") or "").casefold():
        if not exists:
            raise ValueError("Give the ID of the published preset to remove.")
        return PresetContribution(
            preset=json.loads(current.read_text()),
            deletions=[preset_repo_path(identifier), *_folder_files(root, identifier)],
            is_modification=True,
            removed=True,
            reason=reason,
        )
    preset = _file(_field(body, "file") or "", download)
    preset["preset"] = _metadata(body, identifier, preset)
    files, attached = _images(body, preset, download)
    if files and "[x]" not in (_field(body, "licence") or "").casefold():
        raise ValueError(
            "Confirm you made the attached images or may share them under the "
            "repository licence."
        )
    for path, url in preset_art_urls(preset):
        if art_source(url) is None:
            raise ValueError(
                f"Link {path} to TMDB, TPDb, fanart.tv or TVDB, or attach the image."
            )
        image = preset_image_path(url)
        if image and image not in files and not (root / image).is_file():
            raise ValueError(f"Attach the image {url} links, or link another.")
    preset = validate_preset(preset, published=True)
    path = preset_repo_path(identifier)
    text = json.dumps(preset, indent=2, ensure_ascii=False) + "\n"
    kept = {
        image for _, url in preset_art_urls(preset) if (image := preset_image_path(url))
    }
    old = _folder_files(root, identifier)
    additions: dict[str, str | bytes] = {
        name: data
        for name, data in files.items()
        if not (root / name).is_file() or (root / name).read_bytes() != data
    }
    if not current.is_file() or current.read_text() != text:
        additions[path] = text
    deletions = [name for name in old if name not in kept]
    if not additions and not deletions:
        raise NoChangesError(
            f"OvertureDB already holds the {preset['preset']['title']} preset as given."
        )
    return PresetContribution(
        preset=preset,
        additions=additions,
        deletions=deletions,
        is_modification=exists,
        reason=reason,
        attached=attached,
    )
