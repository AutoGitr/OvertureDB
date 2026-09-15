# Contributing to OvertureDB

OvertureDB accepts curated selections, not arbitrary media uploads. The repository
stores metadata, image URLs, and YouTube IDs; never attach copyrighted image or
audio files to a contribution.

## Selection criteria

- Use stable external IDs for the exact movie or show.
- Prefer high-resolution, correctly framed artwork from the allowlisted providers.
- Posters should identify the title clearly and avoid unrelated promotional text.
- Backgrounds should work as wide artwork without critical content at the edges.
- A show's season poster set should be visually coherent.
- Theme selections should identify the work, contain no unrelated commentary, and
  normally run between 30 seconds and five minutes.
- Do not submit malicious, deceptive, explicit, hateful, or rights-infringing
  destinations.

Review is curatorial. A structurally valid contribution may still be declined when
the selection is low quality, duplicative, misleading, or inconsistent with an
existing set.

## Submit a selection

Use the repository contribution issue form. Supply the media type, title, year,
at least one external ID, desired artwork URLs, optional season posters, and an
11-character YouTube ID where applicable. A moderator can ask the constrained bot
to create a pull request after reviewing the issue.

### Moderator Bot Commands

A moderator can trigger OvertureDB-bot actions by commenting on the contribution issue:

- `@OvertureDB-bot approve` - creates a pull request for this contribution.

Curated dataset JSON changes are accepted through that bot workflow. Automated
ThemerrDB imports maintain secondary themes separately. This keeps filenames,
schema validation, and the relationship between an issue and its pull request
consistent. Changes to schemas, validators, workflows, documentation, notices, or
licenses use an ordinary maintainer pull request.

## Validate changes

Use Python 3.14.7 managed with `uv`:

```sh
uv lock --check
uv run ruff check .github/scripts
uv run ruff format --check .github/scripts
uv run python -m unittest discover -s .github/scripts -p 'test_*.py'
uv run python .github/scripts/catalog.py validate
uv run python .github/scripts/catalog.py validate --check-urls --entry data/movies/tmdb-123.json
```

The pull-request guard validates the complete dataset and performs live checks for
changed entries. The publication workflow repeats all tests and validates the
complete catalog's structure and identities. Live URL checks remain available
through `--check-urls` without blocking publication on remote availability.

## Corrections and removal requests

Open an issue and identify the entry, field, reason, and supporting source. Use the
same process for dead links, changed upstream content, incorrect IDs, attribution
or licensing concerns, and removal requests from a rights holder. Do not include
private personal information.

Maintainers preserve the discussion and corrective commit in Git history. The live
catalog is rebuilt from corrected `main`; it does not continue serving the removed
entry. Security-sensitive reports follow `.github/SECURITY.md`.

## Contract changes

Contract changes require coordinated Overture and OvertureDB pull requests. Change
the canonical schema and Python contract here, update tests, regenerate Overture's
bundled contract (via `uv run python scripts/dataset_contract.py`, see [Overture Development Guide](../Overture/docs/development.md#schema-contracts-pipeline)), and increment `schema_version` when compatibility changes. Do not
add compatibility shims for catalog formats that were never publicly released.
