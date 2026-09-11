# OvertureDB

OvertureDB is the public, opt-in catalog of curated artwork and theme selections
used by [Overture](https://github.com/AutoGitr/Overture). It publishes metadata and
links; it does not redistribute the linked artwork or YouTube audio.

## Published artifacts

The GitHub Pages publication contains:

- `catalog.json` and deterministic `catalog.json.gz`;
- `SHA256SUMS` for byte-level integrity checks;
- the catalog and entry JSON schemas;
- the source Git revision and its UTC commit timestamp; and
- third-party notices and applicable license texts.

Hashes detect accidental or unexpected byte changes; they do not prove who
published an artifact. Consumers must download from the repository's documented
HTTPS Pages origin.

## Contract

`schema/entry.schema.json`, `schema/catalog.schema.json`, and `schema/contract.py`
are the canonical version 2 contract, shared with Overture through its
`scripts/dataset_contract.py` generator. Change this source first, regenerate the
app's bundled copy, and land both changes together. No other catalog format is
served or supported.

Entries have a nonblank title of at most 200 characters, a nullable four-digit
year, and at least one external ID. Numeric IDs are positive signed 64-bit
integers; IMDb IDs use `tt` followed by digits. IDs are unique within each media
type, so a movie and show can legitimately share a numeric ID. Shows require a
season list with unique nonnegative season numbers; movies cannot have seasons.
Unknown properties, wrong scalar types, and duplicate identities reject the
entire catalog.

Files live directly in `data/movies` or `data/shows`, named for one of their IDs,
such as `tmdb-123.json`, `tvdb-123.json`, or `imdb-tt123.json`. Artwork must use a
public HTTPS destination on the allowlist in `.github/scripts/catalog.py`. Live
validation checks every redirect and reads only enough bytes to verify JPEG or
PNG content.

## Provenance and licensing

Artwork URLs identify the remote source; YouTube IDs identify the selected video.
An entry derived from another catalog, database, or authored publication must add
the optional `sources` array with that source's name, public HTTPS URL, and license.
The source URL and every redirect are checked before publication. Original
curatorial choices need no artificial source record, but contributors remain
responsible for the accuracy of IDs and links.

Repository-level derivations and license obligations are recorded in
`THIRD_PARTY_NOTICES.md` and `licenses/`. A catalog entry does not grant rights to
downloaded media. Consumers and contributors must follow the source service's
terms and applicable law.

## Validation and publication

Use Python 3.14.7:

```sh
python -m pip install -r .github/scripts/requirements.txt
ruff check .github/scripts
ruff format --check .github/scripts
python -m unittest discover -s .github/scripts -p 'test_*.py'
python .github/scripts/catalog.py validate
python .github/scripts/catalog.py validate --check-urls
python .github/scripts/catalog.py build
```

Every contribution validates the complete dataset's structure and identities.
`--entry data/movies/tmdb-123.json` limits only the live URL checks. Publication
validates all entries, artwork, attribution links, and tests before uploading a
Pages artifact. Pushes to `main`, the daily schedule, and manual runs publish the
current `main`. Build jobs have read-only repository permissions; only the
deployment job receives Pages and identity-token write permissions.

The builder sorts entries, uses canonical JSON encoding and a zero gzip timestamp,
and derives `generated_at` from the source commit. It refuses a dirty checkout so
`source_revision` identifies every input byte. Identical source and toolchain
inputs therefore produce identical artifacts.

## Schema versions

The single Pages URL serves the current schema only. Increment `schema_version`
for an incompatible field, type, validation, identity, or semantic change. Update
Overture to understand that version before switching the publisher. Compatible
clarifications that do not alter accepted data may remain on the current version.

Old schemas are not retained at the live URL. A consumer must reject unsupported
versions before changing local data, which Overture does. Published catalog
artifacts remain reproducible from their Git revision.

## Contributing and corrections

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for selection criteria, entry format,
attribution rules, and local checks. Contributions are submitted through the issue
form and converted into a constrained bot-authored pull request for review.

Report incorrect IDs, dead or changed links, inappropriate selections, licensing
concerns, or removal requests through a new issue. For a vulnerability in the
validation or publication pipeline, use the private process in
`.github/SECURITY.md` instead of disclosing it in an issue.
