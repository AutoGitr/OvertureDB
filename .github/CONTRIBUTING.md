# Contributing to OvertureDB

For artwork and themes, use the [selection guidelines](../docs/selection-guidelines.md).
For GitHub permissions, labels and rollout, see [repository setup](SETUP.md).

## Development

Use Python 3.14.7 and uv. The same read-only gate runs locally and in CI:

```sh
uv sync --locked
```

```sh
bash scripts/pre-commit-check.sh
```

It checks the lockfile, Ruff lint/formatting, strict Pyright types, unit tests,
workflow invariants, and every dataset entry. On Windows, run it in Git Bash.
To format changes, use `uv run --locked ruff format scripts schema`.

PR checks and a daily scheduled guard also run `uv audit --locked`, covering
direct, transitive and development dependencies. Run it locally when changing
dependencies; it requires network access and currently emits uv's experimental
feature notice. No vulnerabilities are ignored.

### Lint and type exceptions

Production scripts and tests both pass strict Pyright. Ruff detects unused
`noqa` comments, and Pyright rejects unnecessary type-ignore comments. There are
no excluded test files or global assertion exemptions. CLI entry points allow
`T201` because printing results/errors is their interface.

The remaining inline exceptions are deliberate and documented at their call sites:
`S603` for fixed executables with argument arrays and no shell; `S310` for HTTPS
requests checked against allowed hosts and public addresses, including redirects;
and `S314` for parsing locally generated SVG in tests. The two narrow Pyright
exceptions in `schema/contract.py` cover incomplete upstream jsonschema factory
and validation stubs. They do not suppress data validation or other diagnostics.

Optional network checks and publication from a clean checkout:

```sh
uv run --locked python scripts/catalog.py validate --check-urls --entry data/movies/tmdb-123.json
```

```sh
uv run --locked python scripts/catalog.py build
```

The build produces catalog JSON/gzip, schemas, licenses, checksums, and statistics
in `public/`. Its revision and timestamp come from the source commit. Tests verify
reproducibility without requiring a clean working tree. Pages updates after
relevant merges and daily as a fallback.

## Contributions

Use exactly one `movie`, `show`, or `bulk` label together with `contribution`.
Preview comments show validation failures, clickable selections and the proposed
diff. Replacing curated media requires a reason. Bulk archives add only missing
values and never modify imported ThemerrDB themes. If any record fails validation,
no files are written. Limits are 10 MB downloaded, 1,000 JSON entries, 1 MB per
entry, and 50 MB of uncompressed JSON.

A collaborator with write, maintain or admin permission can comment:

```text
@OvertureDB-bot approve
```

```text
@OvertureDB-bot reject
```

Append a reason to the reject command on the same line when useful.

Approval creates a bot PR. Single-entry and ThemerrDB PRs request auto-merge only
when `contribution-guard` is enforced on main; bulk PRs require manual merging.
Edits after approval require a fresh command. Labels alone never authorize a PR.
One open ThemerrDB import PR is allowed at a time; review it before the next import.
The import PR records the exact upstream commit.

Code, schema, documentation and workflow changes use ordinary reviewed PRs.
Dataset PRs may only contain canonical JSON files from the bot's internal branches.

## Shared schema

`schema/entry.schema.json`, `schema/catalog.schema.json` and `schema/contract.py`
are shared with Overture. After changing them, validate existing data and run,
from the sibling Overture checkout:

```sh
uv run python scripts/dataset_contract.py ../OvertureDB
```

Submit both repositories' changes together. Increment `SCHEMA_VERSION` for
breaking changes; do not introduce compatibility shims for unreleased formats.

## Corrections and removal requests

Use a movie/show contribution to replace artwork or themes. For wrong identifiers,
rights-holder requests, or entry removal, open a
[correction request](https://github.com/AutoGitr/OvertureDB/issues/new?template=correction.yml)
with the file path and reason. Identifier replacement and deletion are deliberately
blocked by the contribution guard: maintainers must handle them as a separately
reviewed maintenance/policy change, not an approval-command shortcut.
Report security vulnerabilities privately using [SECURITY.md](SECURITY.md).
