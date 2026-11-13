---
sidebar_position: 2
title: Development
description: Running the checks, the code layout and the schema shared with Overture.
---

# Development

Use the pinned Python and uv versions. Python is pinned exactly in
`requires-python` and `.python-version`; update both together with `uv.lock`,
including for patch releases. Renovate's pinning policy is intentional.

The same read-only gate runs locally and in CI:

```sh
uv sync --locked
```

```sh
bash scripts/pre-commit-check.sh
```

It checks the lockfile, Ruff lint and formatting, strict Pyright types, the
pytest suite with branch coverage, workflow invariants, and every catalog
entry. On Windows, run it in Git Bash. To run it on every commit, enable the
Git hooks once per clone with `git config core.hooksPath .githooks`. To
format changes, use `uv run --locked ruff format scripts schema tests`.

PR checks and a weekly scheduled guard also run `uv audit --locked`, covering
direct, transitive and development dependencies. Run it locally when changing
dependencies; it requires network access and currently emits uv's
experimental feature notice. No vulnerabilities are ignored.

## Optional network checks

Validate an entry's links, or build the catalog as the daily publication does,
from a clean checkout:

```sh
uv run --locked python -m scripts.catalog validate --check-urls --entry data/movies/tmdb-123.json
```

```sh
uv run --locked python -m scripts.catalog build
```

The build produces the JSON Lines catalog (a header line, then one entry per
line; plain and gzip), schemas, licenses, checksums and statistics in
`public/`. Its revision and timestamp come from the source commit. Tests
verify reproducibility without requiring a clean working tree. See
[The catalog](../catalog.md).

## Code layout

The workflows keep triggers, permissions and token creation in YAML. Tested
Python scripts own validation, review formatting and publication; `scripts`
and `schema` are packages, so run every script from the repository root as
`python -m scripts.<name>`.

- `scripts/github.py` names the bot and makes every GitHub API call and push.
- Every script reads and writes entries through `scripts/catalog.py`:
  `EntryIndex` finds an entry by any of its identifiers, `new_entry` builds
  one with every field, `merge_ids` adds identifiers and refuses conflicting
  ones, `ENTRY_FILE` matches entry file paths, and `entry_path`,
  `planned_file_changes` and `write_changes` decide where and how an entry is
  written.
- Rules on entry values (ID patterns, title length, year range, the TMDB,
  TVDB, IMDb identifier preference that names entry files) come from
  `schema/contract.py`.

Only the workflows push.

## Lint and type exceptions

Production scripts and tests both pass strict Pyright. Ruff detects unused
`noqa` comments, and Pyright rejects unnecessary type-ignore comments. No test
file is excluded; tests allow `S101` because pytest checks plain assertions.
CLI entry points allow `T201` because printing results and errors is their
interface.

The remaining inline exceptions are deliberate and documented at their call
sites: `S603` for fixed executables with argument arrays and no shell; `S310`
for HTTPS requests checked against allowed hosts and public addresses,
including redirects; and `S314` for parsing locally generated SVG in tests.
The two narrow Pyright exceptions in `schema/contract.py` cover incomplete
upstream jsonschema factory and validation stubs. They do not suppress data
validation or other diagnostics.

## Shared schema

Every file in `schema/` except the package's `__init__.py`
(`entry.schema.json`, `catalog.schema.json` and `contract.py`) is shared with
Overture, whose CI fails while its copy differs. After changing them, validate
existing data and run, from the sibling Overture checkout:

```sh
uv run python -m scripts.catalog_contract ../OvertureDB
```

Submit both repositories' changes together. Increment `SCHEMA_VERSION` for
breaking changes; do not introduce compatibility shims.

## Documentation

These pages live in `docs/` of the OvertureDB repository and are published
together with Overture's on this site. To preview them, clone Overture beside
OvertureDB and run the site from `Overture/docs`; see
[Documentation](/overture/developer/documentation) in the Overture docs. A
pull request that touches `docs/` builds the whole site, so a broken link
fails before merge.
