"""Validate dataset contributions and build reproducible publication artifacts."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import ipaddress
import json
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any
from urllib.error import HTTPError
from urllib.parse import SplitResult, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from catalog_stats import dashboard, statistics_json, summarize
from github import git

if TYPE_CHECKING:
    from http.client import HTTPMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "schema"))

from contract import (
    SCHEMA_VERSION,
    check_catalog_art_url,
    dump_catalog,
    validate_entries,
    validate_header,
)

ROOT = Path(__file__).resolve().parents[1]


type ExistingIndex = tuple[
    dict[tuple[str, int], Path],
    dict[tuple[str, int], Path],
    dict[tuple[str, str], Path],
    dict[Path, dict[str, Any]],
]


def index_existing_entries(data_dir: Path) -> ExistingIndex:
    """Index existing OvertureDB entries by TMDB, TVDB, and IMDb identities."""
    by_tmdb: dict[tuple[str, int], Path] = {}
    by_tvdb: dict[tuple[str, int], Path] = {}
    by_imdb: dict[tuple[str, str], Path] = {}
    loaded: dict[Path, dict[str, Any]] = {}

    if not data_dir.is_dir():
        raise ValueError(f"Dataset directory does not exist: {data_dir}")

    paths = sorted(data_dir.rglob("*.json"))
    for path, entry in zip(paths, dataset(data_dir.parent), strict=True):
        media_type = entry["media_type"]
        tmdb_id = entry.get("tmdb_id")
        tvdb_id = entry.get("tvdb_id")
        imdb_id = entry.get("imdb_id")

        if tmdb_id is not None:
            by_tmdb[(media_type, tmdb_id)] = path
        if tvdb_id is not None:
            by_tvdb[(media_type, tvdb_id)] = path
        if imdb_id is not None:
            by_imdb[(media_type, imdb_id)] = path
        loaded[path] = entry

    return by_tmdb, by_tvdb, by_imdb, loaded


def find_existing_entry(
    entry: dict[str, Any],
    by_tmdb: dict[tuple[str, int], Path],
    by_tvdb: dict[tuple[str, int], Path],
    by_imdb: dict[tuple[str, str], Path],
) -> Path | None:
    """Locate an existing entry file across TMDB, TVDB, or IMDb identifiers."""
    media_type = entry["media_type"]
    tmdb_id = entry.get("tmdb_id")
    tvdb_id = entry.get("tvdb_id")
    imdb_id = entry.get("imdb_id")

    matches: set[Path] = set()
    if tmdb_id is not None and (media_type, tmdb_id) in by_tmdb:
        matches.add(by_tmdb[(media_type, tmdb_id)])
    if tvdb_id is not None and (media_type, tvdb_id) in by_tvdb:
        matches.add(by_tvdb[(media_type, tvdb_id)])
    if imdb_id is not None and (media_type, imdb_id) in by_imdb:
        matches.add(by_imdb[(media_type, imdb_id)])

    if len(matches) > 1:
        raise ValueError(
            f"Conflicting existing files matched for entry: {[p.name for p in matches]}"
        )
    return next(iter(matches), None)


def determine_canonical_path(
    media_type: str,
    tmdb_id: int | None,
    tvdb_id: int | None,
    imdb_id: str | None,
    data_dir: Path,
) -> Path:
    folder = "movies" if media_type == "movie" else "shows"
    providers = (
        (
            ("tvdb", tvdb_id),
            ("tmdb", tmdb_id),
            ("imdb", imdb_id),
        )
        if media_type == "show"
        else (
            ("tmdb", tmdb_id),
            ("tvdb", tvdb_id),
            ("imdb", imdb_id),
        )
    )

    for prefix, val in providers:
        if val is not None:
            return data_dir / folder / f"{prefix}-{val}.json"

    raise ValueError(f"No valid identifier found to construct {media_type} filename.")


def dataset(root: Path = ROOT) -> list[dict[str, Any]]:
    if not (root / "data").is_dir():
        raise ValueError("Dataset directory does not exist")
    paths = sorted((root / "data").rglob("*.json"))
    resolved_data = root.resolve() / "data"
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(resolved_data):
            raise ValueError(f"Dataset entry must be a regular local file: {path}")
    entries = validate_entries(
        [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    )
    for path, entry in zip(paths, entries, strict=True):
        validate_entry_path(path, entry, root)
    return entries


def validate_entry_path(path: Path, entry: dict[str, Any], root: Path) -> None:
    folder = "movies" if entry["media_type"] == "movie" else "shows"
    if path.parent != root / "data" / folder:
        raise ValueError(f"{path.name} belongs in data/{folder}")
    prefix, _, value = path.stem.partition("-")
    field = {"tmdb": "tmdb_id", "tvdb": "tvdb_id", "imdb": "imdb_id"}.get(prefix)
    if not field or entry[field] is None or str(entry[field]) != value:
        raise ValueError(f"{path.name} does not match an entry identifier")


def write_changes(
    original: dict[Path, dict[str, Any]],
    planned: dict[Path, dict[str, Any]],
    root: Path,
) -> None:
    """Validate the whole plan before writing any changed entry."""
    validate_entries(list(planned.values()))
    for path, entry in planned.items():
        validate_entry_path(path, entry, root)
    for path, entry in planned.items():
        if entry != original.get(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(entry, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )


def art_urls(entries: list[dict[str, Any]]) -> set[str]:
    return {
        url
        for entry in entries
        for url in (
            entry["poster_url"],
            entry["background_url"],
            *(season["poster_url"] for season in entry.get("seasons", [])),
        )
        if url is not None
    }


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


def check_art_url(url: str, *, max_retries: int = 5) -> None:
    check_art_destination(url)
    # HTTPS and host validated above; ArtRedirectHandler validates each redirect.
    request = Request(  # noqa: S310
        url, headers={"Range": "bytes=0-15", "User-Agent": "OvertureDB"}
    )
    opener = build_opener(ArtRedirectHandler())
    for attempt in range(max_retries):
        try:
            with opener.open(request, timeout=20) as response:
                content_type = response.headers.get_content_type()
                signature = response.read(16)
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
            and signature.startswith(b"\xff\xd8\xff")
        )
        or (content_type == "image/png" and signature.startswith(b"\x89PNG\r\n\x1a\n"))
    ):
        raise ValueError("Artwork response is not a JPEG or PNG image")


def build(output: Path, *, root: Path = ROOT, revision: str, generated_at: str) -> None:
    entries = sorted(
        dataset(root),
        key=lambda entry: (
            entry["media_type"],
            entry["title"],
            entry["tvdb_id"] or 0,
            entry["tmdb_id"] or 0,
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
        encoding="utf-8",
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
        encoding="utf-8",
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
                    [json.loads(path.read_text(encoding="utf-8")) for path in paths]
                )
                for path, entry in zip(paths, entries, strict=True):
                    validate_entry_path(path, entry, root)
            else:
                entries = dataset()
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
