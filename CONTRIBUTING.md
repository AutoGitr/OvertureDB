# Contributing to OvertureDB

Thank you for helping improve OvertureDB. This document outlines development standards, validation tools, schema contract management, and contribution workflows.

> [!TIP]
> **Looking to contribute artwork or theme music?**  
> Read the **[Selection Guidelines](docs/selection-guidelines.md)** for detailed curation standards, resolution requirements, allowed sources, Criterion rules, and established poster sets.

---

## Code & Tooling Guidelines

OvertureDB's build scripts, validation suite, and import automation are written in Python 3.14.7 and managed with Astral's `uv`.

### Tooling Conventions
- **No Direct `pip`**: Always use `uv` for dependency management.
- **Strict Linting & Formatting**: Enforced via Ruff.
- **Reproducible Builds**: All catalog artifacts (`catalog.json`, `catalog.json.gz`, and `SHA256SUMS`) must build deterministically.

### Local Environment Setup

Ensure Python 3.14.7 and `uv` are installed, then sync dependencies:

```sh
uv sync
```

### Validation & Testing Commands

Always run the full test suite and linters before submitting a pull request:

```sh
# 1. Verify lockfile integrity
uv lock --check

# 2. Lint and format checks
uv run ruff check .github/scripts
uv run ruff format --check .github/scripts

# 3. Run unit tests
uv run python -m unittest discover -s .github/scripts -p 'test_*.py'

# 4. Validate dataset schema and integrity
uv run python .github/scripts/catalog.py validate

# 5. (Optional) Run live URL check against a single entry
uv run python .github/scripts/catalog.py validate --check-urls --entry data/movies/tmdb-123.json

# 6. Test artifact build output
uv run python .github/scripts/catalog.py build
```

---

## Schema Contracts & Overture Synchronization

OvertureDB defines the canonical JSON schemas and validation contracts shared with [Overture](https://github.com/AutoGitr/Overture).

- Canonical definitions live in:
  - `schema/entry.schema.json`
  - `schema/catalog.schema.json`
  - `schema/contract.py`
- When modifying schemas:
  1. Update the canonical contract in `OvertureDB/schema/`.
  2. Run the test suite to confirm schema compliance.
  3. Increment `SCHEMA_VERSION` if any incompatible validation, type, identity, or semantic changes are introduced.
  4. Regenerate Overture's bundled contract (`uv run python scripts/dataset_contract.py` in the Overture repository) and land both pull requests together.
- Never introduce legacy shims or backwards-compatibility wrappers for catalog versions that were never publicly released.

---

## Automation & Bot Workflows

Dataset contributions are converted into automated pull requests via `@OvertureDB-bot`.

### Moderator Bot Commands
Maintainers manage contribution issues by commenting:
- `@OvertureDB-bot approve` — Generates a bot-authored pull request with verified changes and merges the submission.
- `@OvertureDB-bot reject [reason]` — Closes the issue as not planned with the provided reason recorded in the comment.

### Maintainer Workflow
Maintainers can directly edit an issue description to fix typos or adjust URLs. Saving changes automatically triggers the preview workflow to re-verify the selection before running `@OvertureDB-bot approve`.

Non-dataset changes (updates to schemas, GitHub Actions, scripts, or documentation) use standard GitHub pull requests.

---

## Corrections and Removal Requests

To report incorrect IDs, dead links, changed upstream media, attribution concerns, or removal requests from rights holders:
1. Open a new issue in the repository.
2. Specify the entry filename, affected fields, and relevant justification.
3. Maintainers will verify the request and update or remove the entry. The published catalog is rebuilt automatically upon merge.

---

## Security Policy

For security vulnerabilities (such as SSRF, redirect bypasses, workflow privilege escalation, or artifact tampering), follow the private disclosure process in **[.github/SECURITY.md](.github/SECURITY.md)**. Do not disclose vulnerabilities in public issues.
