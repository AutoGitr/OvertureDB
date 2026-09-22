# Contributing to OvertureDB

This document covers code, schemas, automated workflows, and local validation.

> [!TIP]
> **Contributing artwork or theme music?**
> See the **[Selection Guidelines](../docs/selection-guidelines.md)**.

---

## Tooling & Setup

Code and scripts use Python 3.14.7 managed with `uv`. Do not invoke `pip` directly.

```sh
uv sync
```

---

## Local Validation

Run checks before opening a pull request:

```sh
# Verify lockfile
uv lock --check

# Lint and format
uv run ruff check .github/scripts
uv run ruff format --check .github/scripts

# Run unit tests
uv run python -m unittest discover -s .github/scripts -p 'test_*.py'

# Validate catalog data and schema
uv run python .github/scripts/catalog.py validate

# (Optional) Check live URLs for an entry
uv run python .github/scripts/catalog.py validate --check-urls --entry data/movies/tmdb-123.json

# Test catalog build
uv run python .github/scripts/catalog.py build
```

---

## README statistics

The catalog build also publishes `stats.json`, `stats-light.svg`, and
`stats-dark.svg`. The README loads the SVGs from GitHub Pages, so statistics
refresh with the existing daily publication without committing generated files.
All statistics use the same validated entries and source revision as the catalog,
and their checksums are included in `SHA256SUMS`.

Counting and presentation live in `.github/scripts/catalog_stats.py`. Theme
totals count both source selections; theme coverage counts each title once.
Season totals include specials, but do not claim completeness because expected
season counts are not stored. No historical growth is inferred from release years
or commit dates. After a clean-checkout build, open `public/stats-light.svg` and
`public/stats-dark.svg` to preview both themes.

---

## Schema Contracts

OvertureDB defines canonical JSON schemas shared with [Overture](https://github.com/AutoGitr/Overture):
- `schema/entry.schema.json`
- `schema/catalog.schema.json`
- `schema/contract.py`

When changing schemas:
1. Update schema files in `schema/`.
2. Run unit tests and validate existing entries.
3. Increment `SCHEMA_VERSION` for breaking changes.
4. Regenerate Overture's copy (`uv run python scripts/dataset_contract.py` in the Overture repo) and submit both PRs together.
5. Do not add backwards-compatibility shims for unreleased formats.

---

## Bot Commands & Maintainer Workflows

Dataset submissions are converted into pull requests by `@OvertureDB-bot`.

Maintainers can trigger bot actions in issue comments:
- `@OvertureDB-bot approve` - Generates a bot PR and merges the selection.
- `@OvertureDB-bot reject [reason]` - Closes the issue with the given reason.

Maintainers can edit issue descriptions directly to correct URLs or IDs. Saving re-runs validation before approval.

Non-dataset changes (code, workflows, docs) use standard pull requests.

---

## Corrections & Removals

To report dead links, wrong IDs, or request removal of an entry:
1. Open an issue with the entry filename and reason.
2. Maintainers will review and update or remove the file. The live catalog is updated on merge.
