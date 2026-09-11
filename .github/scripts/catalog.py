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
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import SplitResult, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "schema"))

from contract import SCHEMA_VERSION, validate_catalog, validate_entries  # noqa: E402

ART_HOSTS = {
    "image.tmdb.org",
    "assets.fanart.tv",
    "theposterdb.com",
    "www.theposterdb.com",
    "artworks.thetvdb.com",
    "metadata-static.plex.tv",
}


def dataset(root: Path = ROOT) -> list[dict]:
    paths = sorted((root / "data").rglob("*.json"))
    entries = validate_entries(
        [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    )
    for path, entry in zip(paths, entries, strict=True):
        folder = "movies" if entry["media_type"] == "movie" else "shows"
        if path.parent != root / "data" / folder:
            raise ValueError(f"{path.name} belongs in data/{folder}")
        prefix, _, value = path.stem.partition("-")
        field = {"tmdb": "tmdb_id", "tvdb": "tvdb_id", "imdb": "imdb_id"}.get(prefix)
        if not field or entry[field] is None or str(entry[field]) != value:
            raise ValueError(f"{path.name} does not match an entry identifier")
    return entries


def art_urls(entries: list[dict]) -> set[str]:
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


def source_urls(entries: list[dict]) -> set[str]:
    return {source["url"] for entry in entries for source in entry.get("sources", [])}


def public_https_destination(
    url: str, *, allowed_hosts: set[str] | None = None
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
    parsed = public_https_destination(url, allowed_hosts=ART_HOSTS)
    if parsed.fragment:
        raise ValueError("Artwork URL must not contain a fragment")
    if parsed.hostname in {
        "theposterdb.com",
        "www.theposterdb.com",
    } and not parsed.path.startswith("/api/"):
        raise ValueError("ThePosterDB artwork must use its /api/ path")
    suffix = Path(parsed.path).suffix.lower()
    if suffix and suffix not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("Artwork must be a JPEG or PNG")


def check_source_destination(url: str) -> None:
    public_https_destination(url)


class ArtRedirectHandler(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_art_destination(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SourceRedirectHandler(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_source_destination(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_art_url(url: str) -> None:
    check_art_destination(url)
    request = Request(  # noqa: S310
        url, headers={"Range": "bytes=0-15", "User-Agent": "OvertureDB"}
    )
    with build_opener(ArtRedirectHandler()).open(request, timeout=20) as response:
        content_type = response.headers.get_content_type()
        signature = response.read(16)
    if not (
        (
            content_type in {"image/jpeg", "image/jpg"}
            and signature.startswith(b"\xff\xd8\xff")
        )
        or (content_type == "image/png" and signature.startswith(b"\x89PNG\r\n\x1a\n"))
    ):
        raise ValueError("Artwork response is not a JPEG or PNG image")


def check_source_url(url: str) -> None:
    check_source_destination(url)
    request = Request(  # noqa: S310
        url, headers={"Range": "bytes=0-0", "User-Agent": "OvertureDB"}
    )
    with build_opener(SourceRedirectHandler()).open(request, timeout=20) as response:
        response.read(1)


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
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "source_revision": revision,
        "third_party_notices": "THIRD_PARTY_NOTICES.md",
        "entries": entries,
    }
    validate_catalog(payload)
    notices = root / "THIRD_PARTY_NOTICES.md"
    if not notices.is_file():
        raise ValueError("Third-party notices are required for publication")
    content = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "catalog.json": content,
        "catalog.json.gz": gzip.compress(content, mtime=0),
    }
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


def git_output(*args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise OSError("git is required to build the catalog")
    return subprocess.check_output(  # noqa: S603
        [git, *args], cwd=ROOT, text=True
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--check-urls", action="store_true")
    validate.add_argument(
        "--entry", type=Path, help="Check live URLs only for this contribution"
    )
    publish = commands.add_parser("build")
    publish.add_argument("--output", type=Path, default=ROOT / "public")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            entries = dataset()
            if args.entry:
                target = args.entry.resolve()
                if target not in (ROOT / "data").rglob("*.json"):
                    raise ValueError("Contribution must be an existing dataset entry")
                entries = [json.loads(target.read_text(encoding="utf-8"))]
            if args.check_urls:
                for url in sorted(art_urls(entries)):
                    check_art_url(url)
                for url in sorted(source_urls(entries)):
                    check_source_url(url)
        else:
            if git_output("status", "--porcelain", "--untracked-files=all"):
                raise ValueError(
                    "Build from a clean checkout so source_revision identifies "
                    "the complete source"
                )
            revision = git_output("rev-parse", "HEAD")
            timestamp = git_output("show", "-s", "--format=%ct", "HEAD")
            generated_at = datetime.fromtimestamp(int(timestamp), UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
            build(args.output, revision=revision, generated_at=generated_at)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"Dataset validation failed: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
