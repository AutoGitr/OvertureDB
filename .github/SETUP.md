# Repository setup

Local changes do not change GitHub settings. The public API audit on 2026-09-23
found **Main disabled**, no `security` label, and overlapping `ci` /
`github_actions` labels. Authenticated settings were not accessible.

## Apply in this order

1. In **Settings → Rules → Rulesets → Main**, set **Enforcement status: Active**
   immediately. Keep the existing `contribution-guard` required check. Do not
   allow the contribution App or Renovate to bypass it.
2. Commit and push these local changes yourself. Merge through a pull request
   after `contribution-guard` passes. Codex has not committed or pushed them.
3. Apply labels and the remaining settings below. Run the smoke checks last.

If enabling the ruleset blocks your own code PR because of CODEOWNERS, have
another authorized maintainer review it. If you are the sole maintainer, add only
the repository **Admin role** to the ruleset bypass list with **For pull requests
only**. Use it only for your own reviewed code/configuration PR; wait for the guard
to pass before merging. Do not give Apps bypass access or disable the ruleset.

## Main ruleset

Open [Main](https://github.com/AutoGitr/OvertureDB/settings/rules/16480908).
Use these exact settings (the existing rules already contain most of them):

| Setting | Value |
| --- | --- |
| Enforcement | Active |
| Target | Default branch (`main`) |
| Restrict deletions | On |
| Block force pushes | On |
| Require linear history | On |
| Require a pull request | On |
| Required approvals | 0 |
| Require review from Code Owners | On |
| Dismiss stale approvals | On |
| Require conversation resolution | On |
| Require approval of most recent push | Off |
| Allowed merge method | Squash |
| Required status check | `contribution-guard`, source **GitHub Actions** |
| Require branches up to date | On |
| Do not require checks on creation | Off |
| App bypasses | None |

Zero global approvals allows approved bot dataset PRs to merge after checks.
CODEOWNERS requires review for scripts, workflows, schemas and documentation;
the final `/data/` rule intentionally gives dataset files no code owner.
Bulk PRs still require a maintainer to merge them manually.

## General, Actions, Pages and security

- **Settings → General → Pull Requests:** enable squash merging and auto-merge;
  disable merge commits and rebase merging; enable automatic deletion of head
  branches. The bot enables auto-merge only if the required guard is enforced.
- **Settings → Actions → General → Workflow permissions:** select **Read repository
  contents and packages permissions**. Leave **Allow GitHub Actions to create and
  approve pull requests** disabled: PR creation uses the separate App token.
  Require approval for **all outside collaborators** before running fork PR workflows.
- **Settings → Pages → Build and deployment → Source:** **GitHub Actions**.
  In **Settings → Environments → github-pages**, restrict deployment branches to
  `main` (selected branch rule; no tag rule).
- **Settings → Security → Advanced Security** (or **Code security and analysis**):
  enable private vulnerability reporting, dependency graph, Dependabot alerts,
  secret scanning and push protection where available. Keep Renovate as the
  dependency-update bot; do not add a second Dependabot version-update schedule.
  The dynamic **Dependency Graph** and **Dependabot Updates** workflows are
  GitHub-managed; their presence alone does not mean version updates are duplicated.

## OvertureDB App

In the GitHub App settings, keep repository access limited to **OvertureDB** and
grant only **Contents: Read and write**, **Issues: Read and write**,
**Pull requests: Read and write**, and mandatory **Metadata: Read-only**.
Remove unused Actions, Administration, Workflows and other write permissions.
Accept any pending installation permission update as the repository owner.

In **Settings → Secrets and variables → Actions**, ensure these repository secrets exist:

- `OVERTUREDB_CLIENT_ID`: the App's **Client ID** (not its numeric App ID).
- `OVERTUREDB_APP_PRIVATE_KEY`: the complete PEM private key for that App.

The installed App must open PRs as **`overturedb[bot]`**; that exact login is
checked by the guard. The human comment command remains `@OvertureDB-bot approve`.
Do not paste a key into an issue, workflow file or terminal command history.

## Labels

Install/authenticate the official GitHub CLI (`gh auth login`), then run from
the OvertureDB checkout:

```sh
uv run --locked python .github/scripts/sync_labels.py
uv run --locked python .github/scripts/sync_labels.py --apply
gh label list --repo AutoGitr/OvertureDB --limit 100
```

The first command previews; the second creates/updates the 12 labels in
`.github/labels.json`, including the missing `security` label. Existing issue/PR
labels are preserved. No extra token secret or scheduled label workflow is needed.

Consolidate `github_actions` into `ci`: at **Issues → Labels**, use each label's
linked search to inspect **both open and closed issues and PRs**. On every item
with `github_actions`, add `ci` and remove `github_actions`. Once the old label has
no items, delete it. Search `repo:AutoGitr/OvertureDB label:github_actions` across
both Issues and Pull requests to verify the result.

`accepted` is unused by every workflow; approval comes from permission-checked
commands, not labels. Remove it only after checking its historical assignments.
The generic `duplicate`, `invalid`, `question` and `wontfix` labels are not managed
by automation; retain them if used, or delete them if unassigned. Do not strip
historical labels merely to match the manifest.

## Smoke checks

1. Run `bash scripts/pre-commit-check.sh` locally and **Actions → Contribution Guard
   → Run workflow → main**. Both must pass. On Windows use Git Bash.
2. Run **Import ThemerrDB** with `dry_run: true` and `limit: 10`. Confirm the full
   gate passes and no branch/PR is created.
3. Open a valid movie/show contribution with a real proposed selection. Check that
   its preview updates in place after editing and malformed URLs show an error.
   Add an approval command only when you actually intend to submit that selection.
4. Confirm the resulting single-entry bot PR has `contribution-guard` pending or
   passing and does not merge on a failing check. Bulk PRs must await manual merge.
   Also exercise `@OvertureDB-bot reject reason` on a disposable contribution:
   it should add `rejected`, close it as not planned, and record the reason.
   The last publicly visible failed run was the rejection of issue #183; its
   public annotation only reported exit code 1. The replacement implementation
   uses the REST API's `state_reason: not_planned` and has a rejection regression test.
5. Run **Publish Catalog → main**. Verify the Pages deployment and
   [catalog](https://autogitr.github.io/OvertureDB/catalog.json),
   [checksums](https://autogitr.github.io/OvertureDB/SHA256SUMS), and
   [statistics](https://autogitr.github.io/OvertureDB/stats.json).
   Publication also runs after relevant merges, with a daily scheduled fallback.

If any PR already exists for a contribution issue, review that PR instead of
approving the issue again. If a failed run pushed a branch without creating a PR,
review or delete that unused branch before retrying; the workflow never force-pushes.
