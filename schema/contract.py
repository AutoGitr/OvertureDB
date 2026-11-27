"""The version 1 catalog contract, shared with Overture by catalog_contract.py."""

lazy import json
lazy import re
lazy from collections.abc import Iterable, Iterator
lazy from dataclasses import dataclass
lazy from datetime import datetime
lazy from pathlib import Path
lazy from typing import Any, cast
lazy from urllib.parse import urlsplit

lazy from jsonschema import (
    Draft202012Validator,
    TypeChecker,
    ValidationError,
    validators,
)

SCHEMA_VERSION = 4
SCHEMA_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class _ArtSource:
    """One art source and the shape of the links it serves.

    ``path`` matches every link form the source serves for one image (sizes,
    thumbnails, page and viewer links); ``canonical`` rebuilds the full-size
    image path from its named groups.
    """

    name: str
    label: str
    host: str
    aliases: frozenset[str]
    path: re.Pattern[str]
    canonical: str
    example: str
    catalog: bool = True
    #: The path of a smaller rendition, from the same groups and a ``size``.
    preview: str | None = None


_IMAGE_FILE = r"[^/]+\.(?:jpe?g|png)"
_ART_SOURCES = (
    _ArtSource(
        name="tmdb",
        label="TMDB",
        host="image.tmdb.org",
        aliases=frozenset(
            {"themoviedb.org", "www.themoviedb.org", "media.themoviedb.org"}
        ),
        # Every size (w342, w600_and_h900_bestv2, ...) is the same file.
        path=re.compile(rf"/t/p/[^/]+/(?P<file>{_IMAGE_FILE})", re.IGNORECASE),
        canonical="/t/p/original/{file}",
        example="https://image.tmdb.org/t/p/original/<file>.jpg",
        preview="/t/p/{size}/{file}",
    ),
    _ArtSource(
        name="tpdb",
        label="TPDb",
        host="theposterdb.com",
        aliases=frozenset({"www.theposterdb.com"}),
        path=re.compile(r"/(?:poster|api/assets)/(?P<id>[0-9]+)(?:/view)?/?"),
        canonical="/api/assets/{id}",
        example="https://theposterdb.com/api/assets/<id>",
    ),
    _ArtSource(
        name="fanart",
        label="fanart.tv",
        host="assets.fanart.tv",
        aliases=frozenset({"fanart.tv", "www.fanart.tv"}),
        # /preview/ serves a thumbnail of the /fanart/ original.
        path=re.compile(
            rf"/(?:fanart|preview)/(?P<file>(?:[^/]+/)*{_IMAGE_FILE})", re.IGNORECASE
        ),
        canonical="/fanart/{file}",
        example="https://assets.fanart.tv/fanart/<file>.jpg",
        preview="/preview/{file}",
    ),
    _ArtSource(
        name="tvdb",
        label="TVDB",
        host="artworks.thetvdb.com",
        aliases=frozenset({"thetvdb.com", "www.thetvdb.com"}),
        # A _t suffix or the _cache/ folder serves a thumbnail of the original.
        path=re.compile(
            r"/banners/(?:_cache/)?(?P<folder>(?:[^/]+/)*)"
            r"(?P<stem>[^/]+?)(?:_t)?(?P<ext>\.(?:jpe?g|png))",
            re.IGNORECASE,
        ),
        canonical="/banners/{folder}{stem}{ext}",
        example="https://artworks.thetvdb.com/banners/<path>.jpg",
        preview="/banners/{folder}{stem}_t{ext}",
    ),
    _ArtSource(
        name="plex",
        label="Plex",
        host="metadata-static.plex.tv",
        aliases=frozenset(),
        path=re.compile(rf"/(?P<file>(?:[^/]+/)*{_IMAGE_FILE})", re.IGNORECASE),
        canonical="/{file}",
        example="https://metadata-static.plex.tv/<path>.jpg",
    ),
    _ArtSource(
        name="amazon",
        label="Amazon",
        host="m.media-amazon.com",
        aliases=frozenset({"images-na.ssl-images-amazon.com", "ia.media-imdb.com"}),
        # Size and crop modifiers sit between the id and the extension.
        path=re.compile(
            r"/images/M/(?P<id>[^/.]+)(?:\.[^/]*)?(?P<ext>\.(?:jpe?g|png))",
            re.IGNORECASE,
        ),
        canonical="/images/M/{id}{ext}",
        example="https://m.media-amazon.com/images/M/<id>.jpg",
        catalog=False,
    ),
    # Preset art no other source holds, published from data/presets/ to Pages.
    _ArtSource(
        name="overturedb",
        label="OvertureDB",
        host="autogitr.github.io",
        aliases=frozenset(),
        path=re.compile(
            r"/OvertureDB/presets/(?P<file>[a-z0-9]+(?:-[a-z0-9]+)*/"
            r"[a-z0-9]+(?:-[a-z0-9]+)*\.(?:jpg|png))"
        ),
        canonical="/OvertureDB/presets/{file}",
        example="https://autogitr.github.io/OvertureDB/presets/<preset>/<file>.jpg",
        catalog=False,
    ),
)
_ART_SOURCE_BY_HOST: frozendict[str, _ArtSource] = frozendict(
    {host: source for source in _ART_SOURCES for host in (source.host, *source.aliases)}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)
#: Hosts of the art sources catalog entries may link to.
ART_HOSTS: frozenset[str] = frozenset(
    source.host for source in _ART_SOURCES if source.catalog
)
#: Width-to-height ratios artwork must match, by art type.
ASPECT_RATIOS: frozendict[str, float] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "poster": 2 / 3,
        "background": 16 / 9,
    }
)
#: How far, as a fraction of the target ratio, artwork may be off: it absorbs
#: rounding in fractional resolutions, not off-spec art.
ASPECT_TOLERANCE = 0.01
#: The shortest and longest theme OvertureDB takes, in seconds: a shorter one
#: is a sting rather than a theme, and a longer one a soundtrack.
THEME_SECONDS_RANGE: tuple[int, int] = (20, 600)
#: How the art sources catalog entries may link to are named, in source order.
CATALOG_ART_SOURCE_LABELS: tuple[str, ...] = tuple(
    source.label for source in _ART_SOURCES if source.catalog
)
#: How each art source is named to people, by its name.
ART_SOURCE_LABELS: frozendict[str, str] = frozendict(
    {source.name: source.label for source in _ART_SOURCES}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)


def _art_source_of(url: str) -> _ArtSource | None:
    try:
        hostname = urlsplit(url.strip()).hostname
    except ValueError:
        return None
    return _ART_SOURCE_BY_HOST.get((hostname or "").rstrip("."))


def art_source(url: str) -> str | None:
    """Return the name of the known art source a link points at, if any."""
    source = _art_source_of(url)
    return source.name if source else None


def canonical_art_url(url: str) -> str:
    """Return the one canonical form of an artwork link.

    A link to a known art source, in any form it serves an image under
    (resized, thumbnail, alias host, viewer or page link), becomes that
    image's full-size URL on the source's own host over HTTPS. Links to other
    hosts are returned unchanged once they pass the general checks.

    Raises:
        ValueError: When the link is not a usable http(s) URL, or points at
            a known art source without naming one of its images.
    """
    url = url.strip()
    if any(ord(char) < 33 or char == "\\" for char in url):
        raise ValueError("Artwork link must not contain spaces or backslashes")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ValueError("Artwork link is not a valid URL") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Artwork link must be an http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Artwork link must not contain credentials")
    source = _ART_SOURCE_BY_HOST.get(parts.hostname.rstrip("."))
    if source is None:
        return url
    if port not in (None, 80, 443):
        raise ValueError(f"{source.label} artwork links must use the standard port")
    match = source.path.fullmatch(parts.path)
    if match is None:
        raise ValueError(
            f"{source.label} artwork links must point at an image, "
            f"like {source.example}"
        )
    return f"https://{source.host}{source.canonical.format_map(match.groupdict())}"


def preview_art_url(url: str, *, size: str) -> str | None:
    """Return a smaller rendition of an artwork link, when its source serves one.

    *size* names the rendition for sources that serve several (TMDB's
    ``w342``); others serve one and ignore it.
    """
    source = _art_source_of(url)
    if source is None or source.preview is None:
        return None
    canonical = canonical_art_url(url)
    match = source.path.fullmatch(urlsplit(canonical).path)
    if match is None:
        return None
    return f"https://{source.host}" + source.preview.format_map(
        {**match.groupdict(), "size": size}
    )


def catalog_art_url(url: str) -> str:
    """Return the canonical form of an artwork link the catalog accepts.

    Raises:
        ValueError: When the link is unusable or its source is not one the
            catalog links to.
    """
    canonical = canonical_art_url(url)
    source = _art_source_of(canonical)
    if source is None or not source.catalog:
        *others, last = (item.label for item in _ART_SOURCES if item.catalog)
        raise ValueError(f"Artwork must come from {', '.join(others)} or {last}")
    return canonical


def check_catalog_art_url(url: str) -> None:
    """Require *url* to be the canonical link of catalog artwork.

    Raises:
        ValueError: When it is not, naming the canonical form when one exists.
    """
    canonical = catalog_art_url(url)
    if canonical != url:
        raise ValueError(f"Artwork link must use its canonical form {canonical}")


def theme_length_problem(seconds: int) -> str | None:
    """Why OvertureDB refuses a theme *seconds* long, or None when it takes it."""
    shortest, longest = THEME_SECONDS_RANGE
    if shortest <= seconds <= longest:
        return None
    return (
        f"{seconds} seconds long; OvertureDB takes themes of "
        f"{shortest} seconds to {longest // 60} minutes"
    )


def consistent_poster_problem(url: str) -> str | None:
    """Why *url* cannot be a consistent collection poster, or None when it can."""
    if art_source(url) in CONSISTENT_POSTER_SOURCES:
        return None
    labels = " or ".join(
        source.label
        for source in _ART_SOURCES
        if source.name in CONSISTENT_POSTER_SOURCES
    )
    return f"upload consistent posters to {labels}"


def _schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMA_DIR / name).read_text())


ENTRY_SCHEMA = _schema("entry.schema.json")
CATALOG_SCHEMA = _schema("catalog.schema.json")
Draft202012Validator.check_schema(ENTRY_SCHEMA)
Draft202012Validator.check_schema(CATALOG_SCHEMA)

_ENTRY_FIELDS: dict[str, Any] = ENTRY_SCHEMA["properties"]
#: An 11-character YouTube video ID, as entries store it.
YOUTUBE_ID_PATTERN = re.compile(_ENTRY_FIELDS["youtube_id_overturedb"]["pattern"])
#: An IMDb title ID, as entries store it.
IMDB_ID_PATTERN = re.compile(_ENTRY_FIELDS["imdb_id"]["pattern"])
#: The earliest and latest release year an entry may have.
YEAR_RANGE: tuple[int, int] = (
    _ENTRY_FIELDS["year"]["minimum"],
    _ENTRY_FIELDS["year"]["maximum"],
)
#: The longest title an entry may have.
TITLE_MAX_LENGTH: int = _ENTRY_FIELDS["title"]["maxLength"]
#: The largest TMDB or TVDB ID an entry may have.
MAX_EXTERNAL_ID: int = _ENTRY_FIELDS["tmdb_id"]["maximum"]
#: The fields that identify an entry within its media type, most preferred first.
IDENTITY_FIELDS = ("tmdb_id", "tvdb_id", "imdb_id")

type Identity = tuple[str, str, str | int]

#: The folder under ``data/`` each media type's entries live in.
ENTRY_FOLDERS: frozendict[str, str] = frozendict(
    {"movie": "movies", "show": "shows", "collection": "collections"}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)


def entry_fields(media_type: str) -> tuple[str, ...]:
    """Return the fields an entry of *media_type* carries, in schema order."""
    required = set(ENTRY_SCHEMA["required"])
    for rule in ENTRY_SCHEMA["allOf"]:
        condition = rule.get("if", {}).get("properties", {}).get("media_type", {})
        if condition.get("const") == media_type:
            required.update(rule["then"].get("required", ()))
    return tuple(name for name in _ENTRY_FIELDS if name in required)


#: Fields an entry of each media type may carry beyond the ones it requires.
OPTIONAL_ENTRY_FIELDS: frozendict[str, tuple[str, ...]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "movie": ("no_theme",),
        "show": ("no_theme",),
        "collection": ("no_theme",),
    }
)
#: The poster fields a collection entry carries, in schema order.
COLLECTION_POSTER_FIELDS = (
    "poster_url_individual",
    "poster_url_matte",
    "poster_url_overlay",
)
#: The poster fields an entry may carry, in schema order.
POSTER_FIELDS = ("poster_url", *COLLECTION_POSTER_FIELDS)
#: The top-level artwork link fields an entry may carry, in schema order.
ART_FIELDS = (*POSTER_FIELDS, "background_url")
#: The collection poster fields that follow a shared layout across collections.
CONSISTENT_POSTER_FIELDS = (
    "poster_url_matte",
    "poster_url_overlay",
)
#: The art sources a consistent collection poster may be uploaded to, preferred
#: first: a layout shared across collections needs a source anyone can add to.
CONSISTENT_POSTER_SOURCES = ("tmdb", "tpdb")

#: The issue form that contributes one entry of each media type.
ISSUE_FORMS: frozendict[str, str] = frozendict(
    {"movie": "movie.yml", "show": "show.yml", "collection": "collection.yml"}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)
#: The issue form field each entry field fills; ``seasons`` takes one
#: ``season_num=url`` line per season poster.
ISSUE_FORM_FIELDS: frozendict[str, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "title": "item_title",
        "year": "year",
        "tmdb_id": "tmdb_id",
        "tvdb_id": "tvdb_id",
        "imdb_id": "imdb_id",
        "poster_url": "poster_url",
        "poster_url_individual": "poster_url_individual",
        "poster_url_matte": "poster_url_matte",
        "poster_url_overlay": "poster_url_overlay",
        "background_url": "background_url",
        "seasons": "season_posters",
        "youtube_id_overturedb": "youtube_id",
        "no_theme": "no_theme",
    }
)


def entry_file_stem(entry: dict[str, Any]) -> str:
    """Return the name of an entry's file without ``.json``, such as ``tmdb-603``.

    Entries are named after their most preferred identifier.

    Raises:
        ValueError: When the entry has no identifier to name it after.
    """
    for field in IDENTITY_FIELDS:
        if (value := entry.get(field)) is not None:
            return f"{field.removesuffix('_id')}-{value}"
    raise ValueError("An entry needs a TMDB, TVDB or IMDb ID to be named after")


def parse_entry_file_stem(stem: str) -> tuple[str, str | int]:
    """Return the ``(field, value)`` identity an entry file stem names.

    Raises:
        ValueError: When *stem* is not a name ``entry_file_stem`` produces.
    """
    prefix, _, value = stem.partition("-")
    field = f"{prefix}_id"
    if field == "imdb_id" and IMDB_ID_PATTERN.fullmatch(value):
        return field, value
    if field in {"tmdb_id", "tvdb_id"} and value.isascii() and value.isdigit():
        number = int(value)
        if 0 < number <= MAX_EXTERNAL_ID and str(number) == value:
            return field, number
    raise ValueError(f"Not an entry name: {stem}")


def entry_repo_path(entry: dict[str, Any]) -> str:
    """Return the repository path of an entry's file: ``data/movies/tmdb-603.json``.

    Raises:
        ValueError: When the entry has no identifier to name it after.
    """
    return f"data/{ENTRY_FOLDERS[entry['media_type']]}/{entry_file_stem(entry)}.json"


def entry_identities(entry: dict[str, Any]) -> list[Identity]:
    """Return the ``(media type, field, value)`` keys that identify an entry.

    No two entries of a catalog may share one.
    """
    return [
        (entry["media_type"], field, entry[field])
        for field in IDENTITY_FIELDS
        if entry.get(field) is not None
    ]


def entry_art_urls(entry: dict[str, Any]) -> list[tuple[str, str]]:
    """Return each artwork link of an entry with the path it sits at."""
    fields = [
        *((field, entry.get(field)) for field in ART_FIELDS),
        *(
            (f"seasons.{index}.poster_url", season["poster_url"])
            for index, season in enumerate(entry.get("seasons", []))
        ),
    ]
    return [(path, url) for path, url in fields if url is not None]


# JSON scalar types are preserved: IDs and years are never coerced from strings,
# floats, or booleans before they become database keys.
def _integer(_checker: TypeChecker, value: object) -> bool:
    return type(value) is int


# jsonschema's factory and generated validate method have incomplete type stubs.
_Validator = validators.create(  # pyright: ignore[reportUnknownMemberType]
    meta_schema=Draft202012Validator.META_SCHEMA,
    validators=Draft202012Validator.VALIDATORS,
    type_checker=cast("TypeChecker", Draft202012Validator.TYPE_CHECKER).redefine(
        "integer", _integer
    ),
)
_ENTRY_VALIDATOR = _Validator(ENTRY_SCHEMA)
_CATALOG_VALIDATOR = _Validator(CATALOG_SCHEMA)


def _validate(value: object, *, catalog: bool) -> None:
    validator = _CATALOG_VALIDATOR if catalog else _ENTRY_VALIDATOR
    try:
        # The generated validate method is untyped in jsonschema's stubs.
        validator.validate(value)  # pyright: ignore[reportUnknownMemberType]
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise ValueError(
            f"Catalog contract violation at {path}: {exc.message}"
        ) from exc


def validate_entry(value: object) -> dict[str, Any]:
    _validate(value, catalog=False)
    entry = cast("dict[str, Any]", value)
    _seasons(entry)
    _youtube_ids(entry)
    _art_urls(entry)
    return entry


def _art_urls(entry: dict[str, Any]) -> None:
    for path, url in entry_art_urls(entry):
        try:
            check_catalog_art_url(url)
        except ValueError as exc:
            raise ValueError(f"Catalog contract violation at {path}: {exc}") from exc
    for field in CONSISTENT_POSTER_FIELDS:
        consistent = entry.get(field)
        if consistent is not None and (
            problem := consistent_poster_problem(consistent)
        ):
            raise ValueError(f"Catalog contract violation at {field}: {problem}")


def _youtube_ids(entry: dict[str, Any]) -> None:
    yt_overturedb = entry.get("youtube_id_overturedb")
    if entry.get("no_theme") and yt_overturedb is not None:
        raise ValueError(
            "Catalog contract violation: an entry flagged no_theme has no "
            "youtube_id_overturedb"
        )
    yt_themerrdb = entry.get("youtube_id_themerrdb")
    if (
        yt_overturedb is not None
        and yt_themerrdb is not None
        and yt_overturedb == yt_themerrdb
    ):
        raise ValueError(
            "youtube_id_overturedb and youtube_id_themerrdb must be different"
        )


def _seasons(entry: dict[str, Any]) -> None:
    numbers = [season["season_num"] for season in entry.get("seasons", [])]
    if len(set(numbers)) != len(numbers):
        raise ValueError("Catalog entry contains duplicate season numbers")


def validate_entries(values: list[object]) -> list[dict[str, Any]]:
    entries = [validate_entry(value) for value in values]
    _identities(entries)
    return entries


def _identities(entries: list[dict[str, Any]]) -> None:
    identities: set[Identity] = set()
    for entry in entries:
        for key in entry_identities(entry):
            if key in identities:
                raise ValueError(f"Duplicate catalog identity: {key}")
            identities.add(key)


def validate_header(value: object) -> dict[str, Any]:
    # Check the version first so unsupported catalogs have a clear error.
    if not isinstance(value, dict):
        raise ValueError("Payload is not a OvertureDB catalog")
    header = cast("dict[str, Any]", value)
    if header.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported catalog schema_version")
    _validate(header, catalog=True)
    datetime.fromisoformat(header["generated_at"])
    return header


def dump_catalog(header: dict[str, Any], entries: Iterable[dict[str, Any]]) -> bytes:
    """Serialize JSON Lines: the header record, then one entry per line."""
    return b"".join(
        json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
        for record in (header, *entries)
    )


def read_catalog(lines: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    """Validate the header line, then yield each entry line once it is valid.

    Identity uniqueness spans the whole catalog, so callers enforce it.
    """
    records = iter(lines)
    validate_header(_record(next(records, b"")))
    for line in records:
        yield validate_entry(_record(line))


def _record(line: bytes) -> object:
    return json.loads(line, object_pairs_hook=_unique_keys)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    record = dict(pairs)
    if len(record) != len(pairs):
        raise ValueError("Catalog record repeats a key")
    return record


# Presets: ready-made collections, sets and groups Overture copies into a
# library. Overture's models define their shape: it generates
# preset.schema.json and preset-vocabulary.json, so both sides test the same
# fields, operators, sources and dimensions. A preset says what its
# collections are; how they are shown, their art and themes, and what they
# request or label follow the defaults of the install adding them.

#: The version of the preset file format and of the published presets bundle.
#: It increases only when Overture could not read a preset as it stands.
PRESET_VERSION = 1
#: A preset's ID, which names its file and the folder of its images.
PRESET_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
#: The repository folder preset files and their image folders live in.
PRESET_DIR = "data/presets"
#: The art sources a preset may link to; ``overturedb`` serves its own images.
PRESET_ART_SOURCES = ("tmdb", "tpdb", "fanart", "tvdb", "overturedb")
#: The issue form that contributes a preset.
PRESET_ISSUE_FORM = "preset.yml"
#: The issue form field each part of a preset contribution fills.
PRESET_ISSUE_FORM_FIELDS: frozendict[str, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "id": "preset_id",
        "title": "preset_title",
        "description": "preset_description",
        "category": "category",
        "tags": "tags",
        "file": "preset_file",
        "images": "images",
        "licence": "licence",
        "reason": "modification_reason",
        "remove": "remove",
    }
)

PRESET_SCHEMA = _schema("preset.schema.json")
PRESET_VOCABULARY = _schema("preset-vocabulary.json")
Draft202012Validator.check_schema(PRESET_SCHEMA)
_PRESET_VALIDATOR = _Validator(PRESET_SCHEMA)


def preset_repo_path(preset_id: str) -> str:
    """Return the repository path of a preset's file: ``data/presets/decades.json``."""
    return f"{PRESET_DIR}/{preset_id}.json"


def preset_image_url(preset_id: str, name: str) -> str:
    """Return the published link of an image in a preset's folder."""
    source = next(source for source in _ART_SOURCES if source.name == "overturedb")
    return f"https://{source.host}{source.canonical.format(file=f'{preset_id}/{name}')}"


def preset_image_path(url: str) -> str | None:
    """Return the repository path of a preset image link, or None for other art."""
    if art_source(url) != "overturedb":
        return None
    file = urlsplit(canonical_art_url(url)).path.removeprefix("/OvertureDB/presets/")
    return f"{PRESET_DIR}/{file}"


def _criteria(preset: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yield each criteria group of a preset as (path, media type, group)."""
    for index, collection in enumerate(preset.get("collections", [])):
        for media_type, group in collection["criteria"].items():
            yield f"collections.{index}.criteria.{media_type}", media_type, group
    for index, group in enumerate(preset.get("groups", [])):
        generator = group.get("generator")
        if generator is None:
            continue
        path = f"groups.{index}.generator"
        groups = [
            (f"{path}.criteria", generator.get("criteria")),
            *(
                (f"{path}.custom_values.{number}.criteria", value["criteria"])
                for number, value in enumerate(generator.get("custom_values", []))
            ),
        ]
        for media_type in generator["media_types"]:
            for where, criteria in groups:
                if criteria is not None:
                    yield where, media_type, criteria


def _conditions(group: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield from group.get("conditions", [])
    for nested in group.get("groups", []):
        yield from _conditions(nested)


def _condition_problem(condition: dict[str, Any], media_type: str) -> str | None:
    vocabulary = PRESET_VOCABULARY
    if condition["kind"] == "source":
        source = condition["source"]
        spec = vocabulary["sources"][source["type"]]
        if media_type not in spec["media_types"]:
            return f"the {source['type']} source cannot select {media_type}s"
        if (
            source["type"] == "tmdb_chart"
            and media_type not in (vocabulary["charts"][source["chart"]])
        ):
            return f"TMDB has no {source['chart']} chart of {media_type}s"
        return None
    field = vocabulary["fields"][condition["field"]]
    if not field["portable"]:
        return f"{condition['field']} names something only one install has"
    if media_type not in field["media_types"]:
        return f"{condition['field']} cannot be tested on {media_type}s"
    if condition["operator"] not in vocabulary["operators"][field["kind"]]:
        return f"{condition['field']} cannot use the {condition['operator']} operator"
    return None


def _media_types(preset: dict[str, Any]) -> set[str]:
    return {media_type for _, media_type, _ in _criteria(preset)} | {
        media_type
        for group in preset.get("groups", [])
        if (generator := group.get("generator")) is not None
        for media_type in generator["media_types"]
    }


def preset_art_urls(preset: dict[str, Any]) -> list[tuple[str, str]]:
    """Return each artwork link of a preset with the path it sits at."""
    return [
        (f"collections.{index}.art.{slot}.url", art[slot]["url"])
        for index, collection in enumerate(preset.get("collections", []))
        if (art := collection.get("art"))
        for slot in ("poster", "background")
        if art.get(slot)
    ]


def validate_preset(value: object, *, published: bool) -> dict[str, Any]:
    """Validate a preset file, as OvertureDB publishes it when *published*.

    An export from Overture need not describe itself; a published preset
    does, and links only to preset art sources in their canonical form.

    Raises:
        ValueError: Naming the first part of the preset that is refused.
    """
    try:
        # The generated validate method is untyped in jsonschema's stubs.
        _PRESET_VALIDATOR.validate(value)  # pyright: ignore[reportUnknownMemberType]
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise ValueError(f"Preset contract violation at {path}: {exc.message}") from exc
    preset = cast("dict[str, Any]", value)
    _distinct_items(preset)
    for path, media_type, group in _criteria(preset):
        for condition in _conditions(group):
            if problem := _condition_problem(condition, media_type):
                raise ValueError(f"Preset contract violation at {path}: {problem}")
    _set_dimensions(preset)
    if published:
        _published_preset(preset)
    return preset


def _distinct_items(preset: dict[str, Any]) -> None:
    """Require something to add, each once, as Overture's models do."""
    if not preset.get("groups") and not preset.get("collections"):
        raise ValueError("Preset contract violation at root: add a collection or a set")
    for kind, key in (("groups", "name"), ("collections", "title")):
        names = [item[key].strip().casefold() for item in preset.get(kind, [])]
        if len(names) != len(set(names)):
            raise ValueError(
                f"Preset contract violation at {kind}: give each its own {key}"
            )


def _set_dimensions(preset: dict[str, Any]) -> None:
    """Require each set's dimension to hold its media types."""
    for index, group in enumerate(preset.get("groups", [])):
        generator = group.get("generator")
        if generator is None:
            continue
        dimension = PRESET_VOCABULARY["dimensions"][generator["dimension"]]
        for media_type in generator["media_types"]:
            if media_type not in dimension["media_types"]:
                raise ValueError(
                    f"Preset contract violation at groups.{index}.generator: "
                    f"{generator['dimension']} sets cannot hold {media_type}s"
                )


def _published_preset(preset: dict[str, Any]) -> None:
    metadata = preset.get("preset")
    if metadata is None:
        raise ValueError("Preset contract violation at preset: describe the preset")
    if unlisted := _media_types(preset) - set(metadata["media_types"]):
        raise ValueError(
            "Preset contract violation at preset.media_types: add "
            + ", ".join(sorted(unlisted))
        )
    for path, url in preset_art_urls(preset):
        try:
            canonical = canonical_art_url(url)
        except ValueError as exc:
            raise ValueError(f"Preset contract violation at {path}: {exc}") from exc
        if art_source(canonical) not in PRESET_ART_SOURCES:
            labels = [
                source.label
                for source in _ART_SOURCES
                if source.name in PRESET_ART_SOURCES
            ]
            raise ValueError(
                f"Preset contract violation at {path}: artwork must come from "
                f"{', '.join(labels[:-1])} or {labels[-1]}"
            )
        if canonical != url:
            raise ValueError(
                f"Preset contract violation at {path}: artwork link must use "
                f"its canonical form {canonical}"
            )
        image = preset_image_path(url)
        if image is not None and not image.startswith(
            f"{PRESET_DIR}/{metadata['id']}/"
        ):
            raise ValueError(
                f"Preset contract violation at {path}: link the preset's own images"
            )


def preset_requires(preset: dict[str, Any]) -> list[str]:
    """Return the integrations a preset's criteria and sets need, sorted."""
    vocabulary = PRESET_VOCABULARY
    needs: set[str | None] = set()
    for _, _, group in _criteria(preset):
        for condition in _conditions(group):
            needs.add(
                vocabulary["sources"][condition["source"]["type"]]["requires"]
                if condition["kind"] == "source"
                else vocabulary["fields"][condition["field"]]["requires"]
            )
    for group in preset.get("groups", []):
        if (generator := group.get("generator")) is not None:
            needs.add(vocabulary["dimensions"][generator["dimension"]]["requires"])
    return sorted(need for need in needs if need is not None)


def _set(value: Any) -> Any:
    """*value* without the nulls that leave a setting unset, at any depth."""
    if isinstance(value, dict):
        return {
            key: _set(item)
            for key, item in cast("dict[str, Any]", value).items()
            if item is not None
        }
    if isinstance(value, list):
        return [_set(item) for item in cast("list[Any]", value)]
    return value


def preset_text(preset: dict[str, Any]) -> str:
    """Return a preset file as it is written: only what it sets, indented."""
    return json.dumps(_set(preset), indent=2, ensure_ascii=False) + "\n"


def dump_presets(header: dict[str, Any], presets: Iterable[dict[str, Any]]) -> bytes:
    """Serialize the published presets bundle: the header with every preset."""
    return json.dumps(
        {**header, "preset_version": PRESET_VERSION, "presets": list(presets)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def read_presets(data: bytes) -> tuple[dict[str, Any], list[object]]:
    """Return a presets bundle's header and its presets, each still unchecked.

    Each preset is validated on its own, so one an older reader cannot use
    leaves the others usable.

    Raises:
        ValueError: When the bundle is not one this contract reads.
    """
    bundle = _record(data)
    if not isinstance(bundle, dict):
        raise ValueError("Payload is not an OvertureDB presets bundle")
    record = cast("dict[str, Any]", bundle)
    if record.get("preset_version") != PRESET_VERSION:
        raise ValueError("Unsupported presets preset_version")
    presets = record.get("presets")
    if not isinstance(presets, list):
        raise ValueError("Presets bundle has no presets list")
    header = {key: record.get(key) for key in ("generated_at", "source_revision")}
    if not isinstance(header["generated_at"], str) or not isinstance(
        header["source_revision"], str
    ):
        raise ValueError("Presets bundle header is incomplete")
    datetime.fromisoformat(header["generated_at"])
    return header, cast("list[object]", presets)
