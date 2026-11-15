# Maintaining OvertureDB

The repository owner's runbook: the repository settings the automation needs.
Contributors need none of it; their guide is [CONTRIBUTING.md](CONTRIBUTING.md),
and the published pages describe the
[workflows](https://autogitr.github.io/Overture/overturedb/maintainers/workflows)
and [reviewing contributions](https://autogitr.github.io/Overture/overturedb/maintainers/review).

## Repository settings

Keep `contribution-guard` required on `main`, with GitHub Actions as its
source, with strict up-to-date checks and signed commits. Grant the OvertureDB
GitHub App bypass permission on the `main` and `state/*` branch rulesets so it
can commit approved catalog contributions and update `state/health`. The app's
direct writes are gated by `scripts/publication.py` and the shared
`scripts/contribution-check.sh`; the post-push status alone does not enforce
validation before publication. Do not require CodeQL in branch rulesets.

Configure GitHub Pages to deploy with GitHub Actions. Install the OvertureDB
GitHub App on this repository and set `OVERTUREDB_CLIENT_ID` and
`OVERTUREDB_APP_PRIVATE_KEY`. The app needs contents and issues write access.
Protect `state/*` against other non-admin writers. Workflow job permissions
remain separate from that app token.

For the documentation site, also install the app on the Overture repository
with contents write access: the Docs workflow uses it to send Overture a
`repository_dispatch` event after `docs/` changes on `main`, and Overture's
own Docs workflow rebuilds and deploys the site.

Repository labels are defined in `.github/labels.json`. Preview changes with
`uv run --locked python -m scripts.sync_labels`; use `--apply` to reconcile
them or `--check` to detect drift.
