"""Validate dataset contributions and build reproducible publication artifacts."""

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
lazy from typing import IO, Any
lazy from urllib.error import HTTPError
lazy from urllib.parse import SplitResult, urlsplit
lazy from urllib.request import HTTPRedirectHandler, Request, build_opener

lazy from schema.contract import (
    IDENTITY_FIELDS,
    IMDB_ID_PATTERN,
    SCHEMA_VERSION,
    Identity,
    check_catalog_art_url,
    dump_catalog,
    entry_file_stem,
    entry_identities,
    validate_entries,
    validate_header,
)

lazy from .catalog_stats import dashboard, statistics_json, summarize
lazy from .github import git

ROOT = Path(__file__).resolve().parents[1]

#: Width-to-height ratios artwork must match within ASPECT_TOLERANCE.
ASPECT_RATIOS = frozendict({"poster": 2 / 3, "background": 16 / 9})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
ASPECT_TOLERANCE = 0.01
MIN_RESOLUTIONS = frozendict({"poster": (1000, 1500), "background": (1600, 900)})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
MAX_PROBE_BYTES = 256 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: JPEG start-of-frame markers, which carry the dimensions.
_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE}


#: The fields every entry carries, in the order entry files list them.
ENTRY_FIELDS = (
    "media_type",
    "title",
    "year",
    "tmdb_id",
    "tvdb_id",
    "imdb_id",
    "poster_url",
    "background_url",
    "youtube_id_overturedb",
    "youtube_id_themerrdb",
)
#: The folder under ``data/`` each media type's entries live in.
ENTRY_FOLDERS = frozendict({"movie": "movies", "show": "shows"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
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
    entry: dict[str, Any] = dict.fromkeys(ENTRY_FIELDS)
    entry.update(media_type=media_type, title=title, **fields)
    if media_type == "show":
        entry.setdefault("seasons", [])
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
    folder = ENTRY_FOLDERS[entry["media_type"]]
    return data_dir / folder / f"{entry_file_stem(entry)}.json"


def entry_json(entry: dict[str, Any]) -> str:
    """Return the text an entry file holds."""
    return json.dumps(entry, indent=2, ensure_ascii=False) + "\n"


def write_entry_json(path: Path, entry: dict[str, Any]) -> None:
    """Write one entry file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(entry_json(entry), newline="\n")


@dataclass(slots=True)
class EntryIndex:
    """The catalog's entries by file, and the file each identity belongs to."""

    entries: dict[Path, dict[str, Any]] = field(
        default_factory=dict[Path, dict[str, Any]]
    )
    _paths: dict[Identity, Path] = field(default_factory=dict[Identity, Path])

    @classmethod
    def load(cls, root: Path) -> EntryIndex:
        """Index every entry of the dataset under *root*."""
        index = cls()
        for path, entry in dataset(root):
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


def dataset(root: Path = ROOT) -> list[tuple[Path, dict[str, Any]]]:
    """Return every entry file of the dataset with its validated entry."""
    if not (root / "data").is_dir():
        raise ValueError("Dataset directory does not exist")
    paths = sorted((root / "data").rglob("*.json"))
    resolved_data = root.resolve() / "data"
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_data):
            raise ValueError(f"Dataset entry must be a regular local file: {path}")
    entries = validate_entries([json.loads(path.read_text()) for path in paths])
    files = list(zip(paths, entries, strict=True))
    for path, entry in files:
        validate_entry_path(path, entry, root)
    return files


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


def write_changes(
    original: dict[Path, dict[str, Any]],
    planned: dict[Path, dict[str, Any]],
    root: Path,
) -> None:
    """Validate the whole plan before writing changed and removing moved entries."""
    planned_file_changes(original, planned, root)
    for path, entry in planned.items():
        if entry != original.get(path):
            write_entry_json(path, entry)
    for path in original.keys() - planned.keys():
        path.unlink()


def art_fields(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """Return each artwork URL of *entry* with its kind: poster or background."""
    fields = [
        ("poster", entry["poster_url"]),
        ("background", entry["background_url"]),
        *(("poster", season["poster_url"]) for season in entry.get("seasons", [])),
    ]
    return [(kind, url) for kind, url in fields if url is not None]


def art_urls(entries: list[dict[str, Any]]) -> set[str]:
    return {url for entry in entries for _, url in art_fields(entry)}


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


def build(output: Path, *, root: Path = ROOT, revision: str, generated_at: str) -> None:
    entries = sorted(
        (entry for _, entry in dataset(root)),
        key=lambda entry: (
            entry["media_type"],
            entry["title"],
            entry["tmdb_id"] or 0,
            entry["tvdb_id"] or 0,
            entry["imdb_id"] or "",
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
    for name in ("entry.schema.json", "catalog.schema.json"):
        shutil.copyfile(root / "schema" / name, output / "schema" / name)
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>OvertureDB</title>'
        "<h1>OvertureDB</h1><ul>"
        + "".join(
            f'<li><a href="{name}">{name}</a></li>'
            for name in (
                *artifacts,
                "SHA256SUMS",
                "schema/catalog.schema.json",
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
        "--entry", type=Path, nargs="+", help="Validate only these dataset entries"
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
                            "Contribution must be an existing dataset entry"
                        )
                entries = validate_entries(
                    [json.loads(path.read_text()) for path in paths]
                )
                for path, entry in zip(paths, entries, strict=True):
                    validate_entry_path(path, entry, root)
            else:
                entries = [entry for _, entry in dataset()]
            if args.check_urls:
                for url in sorted(art_urls(entries)):
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
        print(f"Dataset validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
