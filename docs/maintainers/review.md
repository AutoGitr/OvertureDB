---
sidebar_position: 1
title: Review
description: Reading a preview, approving or rejecting, and what the bot does on approval.
---

# Review

Contributions arrive as issues of kind `movie`, `show`, `collection` or
`bulk`. The bot posts a preview comment with validation failures, clickable
selections and the proposed diff.

## What the preview checks

Single-entry submissions are rejected for unreachable artwork, new artwork
outside the 1% rule, or a new theme that is removed or private on YouTube or
shorter than 20 seconds or longer than 10 minutes, and warn about new artwork
below the recommended resolution. Bulk archives are not fetched; Dataset
Health reports the same findings for them. Replacing a value or removing an
entry requires a reason.

Bulk archives add missing values and keep imported ThemerrDB themes. Invalid
bulk records block the whole contribution; fix the archive before review.
Limits are 10 MB downloaded, 100,000 JSON entries, 1 MB per entry, and 50 MB
of uncompressed JSON. These are archive safety limits. Review size is based on
the final changed entries, excluding unchanged records and consolidating
repeated records for the same entry. A large export with few changes can fit;
a large set of actual changes must still be split so every change can be
reviewed. Validation errors are reported before preview-size errors.

## Commands

A collaborator with write, maintain or admin permission can comment:

```text
@OvertureDB-bot approve
```

```text
@OvertureDB-bot reject
```

Append a reason to the reject command on the same line when useful.
Maintainers can edit the issue description to adjust URLs or metadata before
approving.

## What approval does

Approval re-evaluates the contribution against `main`, verifies that the
previewed changes have not been altered or superseded by a conflicting update,
and applies the proposed changes in an isolated checkout. The complete
Contribution Guard (tests, coverage, lint, types, dataset validation,
dependency audit and secret scan) must pass before a GitHub-signed commit is
created on `main` and the issue closes. ThemerrDB imports use this same gate.
Failed checks publish nothing.

If `main` advances during validation, dataset changes are rebuilt and
rechecked up to three times. Code changes require a fresh workflow run.
Publication is pinned to the validated base revision; an API failure is never
blindly retried. Unrelated commits to `main` and changes to untouched fields
on a single-entry contribution do not invalidate the preview. Bulk approvals
are bound to the complete planned files; a change to any affected file
requires another review.

If the issue was edited or a reviewed field changed on `main` since the
preview was posted, the bot refreshes the preview comment and requests a new
approval. Keep the approval comment unchanged until processing finishes.
Closing or editing the issue, deleting the approval, or losing write
permission stops pending approval. If a commit fails, the bot leaves the issue
open with recovery instructions.

Maintainers can also refresh an issue from the Contributions workflow's **Run
workflow** action by entering its issue number. Large previews must be split
into smaller contributions so every change fits in the review comment.
