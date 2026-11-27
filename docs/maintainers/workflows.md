---
sidebar_position: 3
title: Workflows
description: The automation that reviews, imports, checks and publishes the catalog.
---

# Workflows

| Workflow           | Purpose                                                                                                                       |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| Contributions      | Validate contribution issues, post preview comments, and commit approved changes to `main`.                                   |
| Contribution Guard | Run the full checks and dependency audit on PRs and pushes to `main`, check presets against Overture, and block non-maintainer catalog PRs. |
| CodeQL             | Scan Python and Actions code when either changes, and weekly; catalog contributions start no analysis.                        |
| Import ThemerrDB   | Import new and updated ThemerrDB themes daily, starting the daily pipeline (or on manual dispatch, optionally limited).     |
| Catalog Health     | Check entries after each import and update the `health` issue.                                                                |
| Publish Catalog    | After each import, validate, build and deploy the catalog to Pages in one deploy for the day. A manual run publishes at once. |
| Docs               | Build the documentation site on pull requests that touch `docs/`, and tell Overture to redeploy it after a change on `main`.  |

## The daily pipeline

Import ThemerrDB runs once a day and calls the rest as reusable workflows:
Catalog Health, then Publish Catalog, whatever the import did, so the day's
approved contributions and imported themes go out in one deploy. Neither is
started by another workflow's run, which a pull request from a fork could
trigger.

Each job names the permissions it needs, and no workflow grants any to all of
its jobs, so a job never holds more than its own; the repository's default
token reads only.

## Catalog Health

Catalog Health checks 200 entries per daily run, new and changed ones first:
artwork reachability, the 1% rule and theme availability as problems, and
artwork below the recommended resolution as warnings, each in its own section
of the `health` issue. Every run also rechecks all entries with reported
findings whose content has changed since their last completed check, outside
that limit. Changes older than 24 hours are included too, so a missed run
cannot leave a fix behind. Transient failures keep the previous findings and
are retried on a later run. Its state lives on the `state/health` branch.
