"""Issue contribution automation. Untrusted input is data, never shell code."""

lazy import re
lazy import time
lazy from http.client import HTTPMessage
lazy from pathlib import Path
lazy from typing import IO, Any
lazy from urllib.request import HTTPRedirectHandler, Request, build_opener

lazy from .catalog import (
    art_fields,
    art_urls,
    aspect_problem,
    check_art_url,
    public_https_destination,
)

ATTACHMENT = re.compile(
    r"https://github\.com/(?:user-attachments/(?:assets/[\w-]+|files/\d+/[\w.~%-]+)"
    r"|[\w.-]+/[\w.-]+/files/\d+/[\w.~%-]+)(?=$|[\s)<>])"
)
ATTACHMENT_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "user-images.githubusercontent.com",
    "github-production-user-asset-6210df.s3.amazonaws.com",
}
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024


def issue_labels(issue: dict[str, Any]) -> set[str]:
    return {label["name"] for label in issue["labels"]}


def contribution_kind(issue: dict[str, Any]) -> str:
    labels = issue_labels(issue)
    kinds = labels & {"movie", "show", "bulk"}
    if issue["state"] != "open" or "pull_request" in issue or len(kinds) != 1:
        raise ValueError("Use one open movie, show or bulk contribution issue.")
    return kinds.pop()


def parse_command(body: str) -> tuple[str, str] | None:
    match = re.fullmatch(
        r"@OvertureDB-bot (approve|reject)(?:[ \t]+([^\r\n]+))?", body.strip()
    )
    if not match or (match[1] == "approve" and match[2]):
        return None
    return match[1], (match[2] or "").strip()


class AttachmentRedirectHandler(HTTPRedirectHandler):
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
        public_https_destination(newurl, allowed_hosts=ATTACHMENT_HOSTS)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_archive(body: str, target: Path) -> None:
    urls = set(ATTACHMENT.findall(body))
    if len(urls) != 1:
        raise ValueError("Attach exactly one GitHub-hosted selections ZIP.")
    url = urls.pop()
    public_https_destination(url, allowed_hosts={"github.com"})
    # HTTPS and host validated above; redirects undergo the same validation.
    request = Request(url, headers={"User-Agent": "OvertureDB"})  # noqa: S310
    opener = build_opener(AttachmentRedirectHandler())
    deadline = time.monotonic() + 60
    total = 0
    with opener.open(request, timeout=20) as response, target.open("wb") as output:
        while chunk := response.read(65536):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES or time.monotonic() > deadline:
                raise ValueError(
                    "Attachment exceeds the 10 MB or 60 second download limit."
                )
            output.write(chunk)


def fenced(value: str, language: str = "text") -> str:
    fence = "`" * max(
        3, max((len(m[0]) + 1 for m in re.finditer(r"`+", value)), default=3)
    )
    return f"{fence}{language}\n{value}\n{fence}"


def check_artwork(entry: dict[str, Any], previous: dict[str, Any] | None) -> None:
    """Check that all artwork is reachable and new artwork follows the 1% rule."""
    existing: set[str] = art_urls([previous]) if previous else set()
    for art_kind, url in sorted(set(art_fields(entry))):
        size = check_art_url(url)
        if url in existing or size is None:
            continue
        if problem := aspect_problem(art_kind, *size):
            raise ValueError(
                f"The {art_kind} {url} is {problem}. "
                "See the 1% rule in the selection guidelines in CONTRIBUTING.md."
            )
