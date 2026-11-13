---
sidebar_position: 3
title: Workflows and settings
description: The automation that reviews, imports, checks and publishes the catalog, and the repository settings it needs.
---

# Workflows and settings

| Workflow           | Purpose                                                                                                                       |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| Contributions      | Validate contribution issues, post preview comments, and commit approved changes to `main`.                                   |
| Contribution Guard | Run the full checks and dependency audit on PRs and pushes to `main`, and block non-maintainer catalog PRs.                   |
| CodeQL             | Scan Python and Actions code when it changes, and both weekly; catalog contributions start no analysis.                       |
| Import ThemerrDB   | Import new and updated ThemerrDB themes daily, starting the daily pipeline (or on manual dispatch with optional dry-run).     |
| Catalog Health     | Check entries after each import and update the `health` issue.                                                                |
| Publish Catalog    | After each import, validate, build and deploy the catalog to Pages in one deploy for the day. A manual run publishes at once. |
| Docs               | Build the documentation site on pull requests that touch `docs/`, and tell Overture to redeploy it after a change on `main`.  |

## The daily pipeline

Import ThemerrDB runs once a day and starts the rest: Catalog Health and
Publish Catalog follow it, so the day's approved contributions and imported
themes go out in one deploy.

## Catalog Health

Catalog Health checks 200 entries per daily run, new and changed ones first:
artwork reachability, the 1% rule and theme availability as problems, and
artwork below the recommended resolution as warnings, each in its own section
of the `health` issue. Every run also rechecks all entries with reported
findings whose content has changed since their last completed check, outside
that limit. Changes older than 24 hours are included too, so a missed run
cannot leave a fix behind. Transient failures keep the previous findings and
are retried on a later run. Its state lives on the `state/health` branch.

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
