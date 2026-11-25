"""Validate catalog contributions and build reproducible publication artifacts."""

lazy import argparse
lazy import gzip
lazy import hashlib
lazy import ipaddress
lazy import json
lazy import re
lazy import shutil
lazy import socket
lazy import struct
lazy import subprocess
lazy import sys
lazy import time
lazy from dataclasses import dataclass, field
lazy from datetime import UTC, datetime
lazy from email.utils import parsedate_to_datetime
lazy from http.client import HTTPMessage
lazy from pathlib import Path
lazy from typing import IO, Any, override
lazy from urllib.error import HTTPError
lazy from urllib.parse import SplitResult, urlencode, urlsplit
lazy from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

lazy from schema.contract import (
    ASPECT_RATIOS,
    ASPECT_TOLERANCE,
    ENTRY_FOLDERS,
    IDENTITY_FIELDS,
    IMDB_ID_PATTERN,
    POSTER_FIELDS,
    PRESET_DIR,
    PRESET_ID_PATTERN,
    SCHEMA_VERSION,
    Identity,
    art_source,
    check_catalog_art_url,
    dump_catalog,
    dump_presets,
    entry_fields,
    entry_identities,
    entry_repo_path,
    preset_art_urls,
    preset_image_path,
    preset_repo_path,
    validate_entries,
    validate_header,
    validate_preset,
)

lazy from .catalog_stats import dashboard, statistics_json, summarize
lazy from .github import git

ROOT = Path(__file__).resolve().parents[1]

MIN_RESOLUTIONS = frozendict({"poster": (1000, 1500), "background": (1280, 720)})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
#: How a contribution review names each artwork field.
ART_LABELS: frozendict[str, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "poster_url": "Poster",
        "poster_url_individual": "Individual poster",
        "poster_url_matte": "Matte poster",
        "poster_url_overlay": "Overlay poster",
        "background_url": "Background",
    }
)
MAX_PROBE_BYTES = 256 * 1024
#: The largest image a preset keeps in the repository.
MAX_PRESET_IMAGE_BYTES = 5 * 1024 * 1024
#: An image file in a preset's folder, as the ``overturedb`` art source links it.
PRESET_IMAGE_FILE = re.compile(rf"{PRESET_ID_PATTERN.pattern}\.(?:jpg|png)")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: JPEG start-of-frame markers, which carry the dimensions.
_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE}


#: The repository path of a canonically named entry file.
_FILE_ID_VALUES = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "tmdb_id": "[0-9]+",
        "tvdb_id": "[0-9]+",
        "imdb_id": IMDB_ID_PATTERN.pattern.strip("^$"),
    }
)
ENTRY_FILE = re.compile(
    rf"data/(?:{'|'.join(ENTRY_FOLDERS.values())})/(?:"
    + "|".join(
        f"{name.removesuffix('_id')}-{value}" for name, value in _FILE_ID_VALUES.items()
    )
    + r")\.json"
)


def new_entry(media_type: str, title: str, **fields: Any) -> dict[str, Any]:
    """Return an entry with every field set; *fields* fills the known ones."""
    entry: dict[str, Any] = {
        name: [] if name == "seasons" else None for name in entry_fields(media_type)
    }
    entry.update(media_type=media_type, title=title, **fields)
    return entry


def merge_ids(entry: dict[str, Any], ids: dict[str, Any]) -> list[str]:
    """Add the identifiers *entry* lacks from *ids*; return what was added.

    Raises:
        ValueError: When *ids* gives an identifier the entry holds another
            value for, since the two then describe different titles.
    """
    added: list[str] = []
    for name in IDENTITY_FIELDS:
        value = ids.get(name)
        if value is None:
            continue
        current = entry.get(name)
        if current is None:
            entry[name] = value
            added.append(f"added {name}={value}")
        elif current != value:
            raise ValueError(
                f"Conflicting {name}: existing={current}, incoming={value}"
            )
    return added


def entry_path(entry: dict[str, Any], data_dir: Path) -> Path:
    """Return where an entry's file belongs: named after its preferred identifier.

    Raises:
        ValueError: When the entry has no identifier to name it after.
    """
    return data_dir.parent / entry_repo_path(entry)


def entry_json(entry: dict[str, Any]) -> str:
    """Return the text an entry file holds."""
    return json.dumps(entry, indent=2, ensure_ascii=False) + "\n"


@dataclass(slots=True)
class EntryIndex:
    """The catalog's entries by file, and the file each identity belongs to."""

    entries: dict[Path, dict[str, Any]] = field(
        default_factory=dict[Path, dict[str, Any]]
    )
    _paths: dict[Identity, Path] = field(default_factory=dict[Identity, Path])

    @classmethod
    def load(cls, root: Path) -> EntryIndex:
        """Index every entry of the catalog under *root*."""
        index = cls()
        for path, entry in entry_files(root):
            index.put(path, entry)
        return index

    def find(self, entry: dict[str, Any]) -> Path | None:
        """Return the file of the entry *entry* shares an identity with.

        Raises:
            ValueError: When its identities belong to different files.
        """
        matches = {
            path
            for identity in entry_identities(entry)
            if (path := self._paths.get(identity)) is not None
        }
        if len(matches) > 1:
            names = sorted(path.name for path in matches)
            raise ValueError(f"Conflicting existing files matched for entry: {names}")
        return next(iter(matches), None)

    def put(self, path: Path, entry: dict[str, Any]) -> None:
        """Record *entry* as the content of *path*, under each of its identities."""
        self.entries[path] = entry
        for identity in entry_identities(entry):
            self._paths[identity] = path

    def update(self, path: Path, entry: dict[str, Any]) -> Path:
        """Replace the entry at *path*, moving it to the file it is now named after.

        Raises:
            ValueError: When another entry already has that file.
        """
        target = entry_path(entry, path.parent.parent)
        if target != path:
            if target in self.entries:
                raise ValueError(f"{target.name} already exists")
            for identity in entry_identities(self.entries.pop(path)):
                self._paths.pop(identity, None)
        self.put(target, entry)
        return target


def entry_files(root: Path = ROOT) -> list[tuple[Path, dict[str, Any]]]:
    """Return every entry file of the catalog with its validated entry."""
    if not (root / "data").is_dir():
        raise ValueError("Data directory does not exist")
    paths = sorted(
        path
        for folder in ENTRY_FOLDERS.values()
        for path in (root / "data" / folder).rglob("*.json")
    )
    resolved_data = root.resolve() / "data"
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_data):
            raise ValueError(f"Catalog entry must be a regular local file: {path}")
    entries = validate_entries([json.loads(path.read_text()) for path in paths])
    files = list(zip(paths, entries, strict=True))
    for path, entry in files:
        validate_entry_path(path, entry, root)
    return files


def preset_files(root: Path = ROOT) -> list[tuple[Path, dict[str, Any]]]:
    """Return every preset file with its validated preset, sorted by ID.

    Each preset's folder holds exactly the images it links, and each is a
    JPEG or PNG of the right shape.
    """
    folder = root / PRESET_DIR
    if not folder.is_dir():
        return []
    resolved = folder.resolve()
    files: list[tuple[Path, dict[str, Any]]] = []
    linked: set[str] = set()
    for path in sorted(folder.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(resolved):
            raise ValueError(f"Preset file must be a regular local file: {path}")
    for path in sorted(folder.glob("*.json")):
        preset = validate_preset(json.loads(path.read_text()), published=True)
        expected = root / preset_repo_path(preset["preset"]["id"])
        if path.resolve() != expected.resolve():
            raise ValueError(
                f"{path.name} must be {preset_repo_path(preset['preset']['id'])}"
            )
        for where, url in preset_art_urls(preset):
            if (image := preset_image_path(url)) is None:
                continue
            kind = "poster" if ".poster." in where else "background"
            preset_image_problem(root / image, kind)
            linked.add(image)
        files.append((path, preset))
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and path.suffix != ".json" and relative not in linked:
            raise ValueError(f"No preset links {relative}")
        if path.is_file() and path.parent != folder and path.suffix == ".json":
            raise ValueError(f"Preset files sit directly in {PRESET_DIR}: {relative}")
    return files


def preset_image_problem(path: Path, kind: str) -> None:
    """Require a preset image to be a JPEG or PNG of *kind*'s shape and size.

    Raises:
        ValueError: Naming the image and what is wrong with it.
    """
    if not path.is_file():
        raise ValueError(f"Preset image is missing: {path.name}")
    if not PRESET_IMAGE_FILE.fullmatch(path.name):
        raise ValueError(f"Name preset images in lowercase words: {path.name}")
    data = path.read_bytes()
    if len(data) > MAX_PRESET_IMAGE_BYTES:
        raise ValueError(f"{path.name} is larger than 5 MB")
    signature = _PNG_SIGNATURE if path.suffix == ".png" else b"\xff\xd8\xff"
    size = image_size(data) if data.startswith(signature) else None
    if size is None:
        raise ValueError(f"{path.name} is not a {path.suffix[1:].upper()} image")
    if problem := aspect_problem(kind, *size) or resolution_warning(kind, *size):
        raise ValueError(f"{path.name}: {problem}")


def validate_entry_path(path: Path, entry: dict[str, Any], root: Path) -> None:
    """Check that an entry file is where ``entry_path`` puts it."""
    expected = entry_path(entry, root / "data")
    if path.resolve() != expected.resolve():
        folder = expected.parent.name
        raise ValueError(f"{path.name} must be data/{folder}/{expected.name}")


def planned_file_changes(
    original: dict[Path, dict[str, Any]],
    planned: dict[Path, dict[str, Any]],
    root: Path,
) -> tuple[dict[str, str], list[str]]:
    """Validate the whole plan and return (additions, deletions) relative to *root*."""
    validate_entries(list(planned.values()))
    for path, entry in planned.items():
        validate_entry_path(path, entry, root)
    additions = {
        path.relative_to(root).as_posix(): entry_json(entry)
        for path, entry in sorted(planned.items())
        if entry != original.get(path)
    }
    deletions = sorted(
        path.relative_to(root).as_posix() for path in original.keys() - planned.keys()
    )
    return additions, deletions


def art_fields(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """Return each artwork URL of *entry* with its kind: poster or background."""
    fields = [
        *(("poster", entry.get(field)) for field in POSTER_FIELDS),
        ("background", entry["background_url"]),
        *(("poster", season["poster_url"]) for season in entry.get("seasons", [])),
    ]
    return [(kind, url) for kind, url in fields if url is not None]


def art_urls(entries: list[dict[str, Any]]) -> set[str]:
    return {url for entry in entries for _, url in art_fields(entry)}


def preset_provider_urls(presets: list[dict[str, Any]]) -> set[str]:
    """Return the art links of presets that another source serves."""
    return {
        url
        for preset in presets
        for _, url in preset_art_urls(preset)
        if art_source(url) != "overturedb"
    }


def image_size(data: bytes) -> tuple[int, int] | None:
    """Return the (width, height) a PNG or JPEG header declares, if it is complete."""
    if data.startswith(_PNG_SIGNATURE):
        if len(data) >= 24 and data[12:16] == b"IHDR":
            width, height = struct.unpack(">II", data[16:24])
            return (width, height) if width and height else None
        return None
    if not data.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 9 <= len(data):
        if data[offset] != 0xFF:
            return None
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
        elif marker == 0x01 or 0xD0 <= marker <= 0xD8:
            offset += 2
        elif marker in {0xD9, 0xDA}:
            return None
        elif marker in _JPEG_SOF:
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return (width, height) if width and height else None
        else:
            length = int.from_bytes(data[offset + 2 : offset + 4])
            if length < 2:
                return None
            offset += 2 + length
    return None


def aspect_problem(kind: str, width: int, height: int) -> str | None:
    """Describe how artwork breaks the 1% rule for its *kind*, or return None."""
    target = ASPECT_RATIOS[kind]
    ratio = width / height if height else 0.0
    if abs(ratio - target) / target <= ASPECT_TOLERANCE:
        return None
    return f"{width}x{height} has ratio {ratio:.3f}, outside 1% of {target:.3f}"


def resolution_warning(kind: str, width: int, height: int) -> str | None:
    """Describe artwork below the recommended resolution for its *kind*, or None."""
    min_width, min_height = MIN_RESOLUTIONS[kind]
    if width >= min_width and height >= min_height:
        return None
    return f"{width}x{height} is below the recommended {min_width}x{min_height}"


class TransientError(Exception):
    """A check could not finish now and may succeed when tried again."""


#: How a YouTube watch page states the video's length, in its player response.
_LENGTH_SECONDS = re.compile(rb'"lengthSeconds":"(\d+)"')
#: More than a watch page holds, so a runaway response cannot exhaust memory.
_WATCH_PAGE_LIMIT = 8 * 1024 * 1024


def _youtube(url: str) -> bytes:
    """Read a fixed YouTube URL, telling a lasting refusal from a passing one."""
    # Callers pass fixed HTTPS YouTube URLs; only the validated video ID varies.
    request = Request(url, headers={"User-Agent": "OvertureDB"})  # noqa: S310 -- fixed HTTPS host
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 -- fixed HTTPS host
            return response.read(_WATCH_PAGE_LIMIT)
    except HTTPError as exc:
        exc.close()
        if exc.code in {401, 403, 404}:
            raise
        raise TransientError(f"YouTube answered HTTP {exc.code}") from exc
    except OSError as exc:
        raise TransientError(str(exc)) from exc


def _watch_url(youtube_id: str) -> str:
    return f"https://www.youtube.com/watch?{urlencode({'v': youtube_id})}"


def theme_problem(youtube_id: str) -> str | None:
    """Ask YouTube's keyless oEmbed endpoint whether a video is still available."""
    try:
        _youtube(
            "https://www.youtube.com/oembed?"
            + urlencode({"format": "json", "url": _watch_url(youtube_id)})
        )
    except HTTPError as exc:
        return "removed" if exc.code == 404 else "private or not embeddable"
    return None


def theme_seconds(youtube_id: str) -> int:
    """Read how long a video is from its YouTube watch page.

    Raises:
        TransientError: When YouTube did not answer or did not say.
    """
    if match := _LENGTH_SECONDS.search(_youtube(_watch_url(youtube_id))):
        return int(match.group(1))
    raise TransientError("YouTube did not say how long the video is")


def public_https_destination(
    url: str,
    *,
    allowed_hosts: set[str] | frozenset[str] | None = None,
) -> SplitResult:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL is malformed") from exc
    host_allowed = allowed_hosts is None or parsed.hostname in allowed_hosts
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or not host_allowed
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or any(ord(char) < 33 for char in url)
        or "\\" in url
    ):
        raise ValueError(
            "URL must use public HTTPS on an allowed host without credentials"
        )
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(row[4][0]).is_global for row in addresses
    ):
        raise ValueError("URL host does not resolve exclusively to public addresses")
    return parsed


def check_art_destination(url: str) -> None:
    """Require catalog artwork whose host resolves only to public addresses."""
    check_catalog_art_url(url)
    public_https_destination(url)


class ArtRedirectHandler(HTTPRedirectHandler):
    max_redirections = 3

    @override
    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        check_art_destination(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def parse_retry_after(header: str | None, default: float = 2.0) -> float:
    if not header:
        return default
    try:
        return max(0.5, float(header))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(header)
        return max(0.5, (dt - datetime.now(UTC)).total_seconds())
    except ValueError, TypeError, OverflowError:
        return default


def check_art_url(url: str, *, max_retries: int = 5) -> tuple[int, int] | None:
    """Check that *url* serves a JPEG or PNG and return its (width, height).

    The size is None when the header is not within MAX_PROBE_BYTES.
    """
    check_art_destination(url)
    # HTTPS and host validated above; ArtRedirectHandler validates each redirect.
    request = Request(  # noqa: S310
        url,
        headers={"Range": f"bytes=0-{MAX_PROBE_BYTES - 1}", "User-Agent": "OvertureDB"},
    )
    opener = build_opener(ArtRedirectHandler())
    for attempt in range(max_retries):
        try:
            with opener.open(request, timeout=20) as response:
                content_type = response.headers.get_content_type()
                data = b""
                size = None
                while len(data) < MAX_PROBE_BYTES and (chunk := response.read(16384)):
                    data += chunk
                    if size := image_size(data):
                        break
            break
        except HTTPError as exc:
            exc.close()
            if exc.code == 429 and attempt < max_retries - 1:
                delay = parse_retry_after(
                    exc.headers.get("Retry-After"), default=2.0**attempt
                )
                time.sleep(min(delay, 60.0))
                continue
            raise
    else:
        raise ValueError("Exceeded maximum retries checking artwork URL")

    if not (
        (
            content_type in {"image/jpeg", "image/jpg"}
            and data.startswith(b"\xff\xd8\xff")
        )
        or (content_type == "image/png" and data.startswith(_PNG_SIGNATURE))
    ) or (size is None and len(data) < MAX_PROBE_BYTES):
        raise ValueError("Artwork response is not a JPEG or PNG image")
    return size


#: The contract schemas published beside the catalog.
PUBLISHED_SCHEMAS = (
    "entry.schema.json",
    "catalog.schema.json",
    "preset.schema.json",
    "preset-vocabulary.json",
)


def build(output: Path, *, root: Path = ROOT, revision: str, generated_at: str) -> None:
    entries = sorted(
        (entry for _, entry in entry_files(root)),
        key=lambda entry: (
            entry["media_type"],
            entry["title"],
            entry["tmdb_id"] or 0,
            entry.get("tvdb_id") or 0,
            entry.get("imdb_id") or "",
        ),
    )
    header = validate_header(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "source_revision": revision,
            "third_party_notices": "THIRD_PARTY_NOTICES.md",
        }
    )
    notices = root / "licenses" / "THIRD_PARTY_NOTICES.md"
    if not notices.is_file():
        raise ValueError("Third-party notices are required for publication")
    content = dump_catalog(header, entries)
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "catalog.jsonl": content,
        "catalog.jsonl.gz": gzip.compress(content, mtime=0),
    }
    presets = [preset for _, preset in preset_files(root)]
    artifacts["presets.json"] = dump_presets(
        {"generated_at": generated_at, "source_revision": revision}, presets
    )
    groups = summarize(entries)
    artifacts["stats.json"] = (
        json.dumps(
            statistics_json(groups, revision=revision, generated_at=generated_at),
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode("utf-8")
    for theme in ("light", "dark"):
        artifacts[f"stats-{theme}.svg"] = dashboard(
            groups, revision=revision, generated_at=generated_at, dark=theme == "dark"
        ).encode("utf-8")
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data in artifacts.items()
        ),
        newline="\n",
    )
    shutil.copyfile(notices, output / notices.name)
    shutil.copytree(root / "licenses", output / "licenses", dirs_exist_ok=True)
    (output / "schema").mkdir(exist_ok=True)
    for name in PUBLISHED_SCHEMAS:
        shutil.copyfile(root / "schema" / name, output / "schema" / name)
    for path in sorted((root / PRESET_DIR).glob("*/*")):
        target = output / "presets" / path.relative_to(root / PRESET_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>OvertureDB</title>'
        "<h1>OvertureDB</h1><ul>"
        + "".join(
            f'<li><a href="{name}">{name}</a></li>'
            for name in (
                *artifacts,
                "SHA256SUMS",
                *(f"schema/{name}" for name in PUBLISHED_SCHEMAS),
                notices.name,
            )
        )
        + "</ul></html>\n",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--check-urls", action="store_true")
    validate.add_argument(
        "--entry", type=Path, nargs="+", help="Validate only these catalog entries"
    )
    publish = commands.add_parser("build")
    publish.add_argument("--output", type=Path, default=ROOT / "public")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            if args.entry:
                root = ROOT.resolve()
                paths = [path.resolve() for path in args.entry]
                for path in paths:
                    if (
                        not path.is_file()
                        or not path.is_relative_to(root / "data")
                        or path.suffix != ".json"
                    ):
                        raise ValueError(
                            "Contribution must be an existing catalog entry"
                        )
                entries = validate_entries(
                    [json.loads(path.read_text()) for path in paths]
                )
                for path, entry in zip(paths, entries, strict=True):
                    validate_entry_path(path, entry, root)
                presets = []
            else:
                entries = [entry for _, entry in entry_files()]
                presets = [preset for _, preset in preset_files()]
            if args.check_urls:
                for url in sorted(art_urls(entries) | preset_provider_urls(presets)):
                    check_art_url(url)
        else:
            if git("status", "--porcelain", "--untracked-files=all"):
                raise ValueError(
                    "Build from a clean checkout so source_revision identifies "
                    "the complete source"
                )
            revision = git("rev-parse", "HEAD")
            timestamp = git("show", "-s", "--format=%ct", "HEAD")
            generated_at = datetime.fromtimestamp(int(timestamp), UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            build(args.output, revision=revision, generated_at=generated_at)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Catalog validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
