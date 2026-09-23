# Repository setup

Local changes do not change GitHub settings. The latest public API check on
2026-09-23 confirms **Main is now active** and the 12 live labels match the
canonical definitions. Authenticated security settings were not accessible;
the recommendations below use your screenshots.

## Apply in this order

1. In **Settings → Rules → Rulesets → Main**, keep **Enforcement status: Active**
   and the existing `contribution-guard` required check. Do not
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

### Your github-pages screenshot

The shown settings are correct: **Selected branches and tags**, exactly one
**branch** rule named `main`, and no tag rules. Leave required reviewers and the
wait timer off for automatic publication. Leave administrator bypass off. Click
**Save protection rules** if you changed them. Branch restrictions are independent
of the Main ruleset; enabling that ruleset is still required.

### Your Advanced Security screenshot

A button reading **Disable** means the feature is already enabled.

| Setting | Desired value / action |
| --- | --- |
| Private vulnerability reporting | Keep enabled |
| Dependency graph | Keep enabled |
| Automatic dependency submission | Keep disabled for this uv-only repository |
| Dependabot alerts | Keep enabled |
| Dependabot rules | Keep zero; no automatic dismissals |
| Dependabot malware alerts | Keep enabled |
| Dependabot security updates | Click **Disable**; Renovate owns update PRs |
| Grouped security updates | Click **Disable** before disabling security updates |
| Dependabot version updates | Keep disabled; do not add `dependabot.yml` |
| CodeQL analysis | **Set up → Default**, select Python and GitHub Actions, default query suite, standard GitHub runner; **Enable CodeQL** |
| AI Scan | Keep off; optional preview, not a required safeguard |
| Copilot Autofix | Keep off; optional suggestions, not automatic protection |
| Check runs failure threshold | Keep **Any** for security and standard alerts |
| Secret Protection | Click **Enable**, then enable **Secret scanning** and **Push protection** |

Configure CodeQL after merging the scripts into `scripts/`. Wait for its first
successful run and confirm both Python and GitHub Actions were analyzed. Then edit
**Main → Add rules → Require code scanning results**, select **CodeQL**, and set
the security and standard alert thresholds to **Any**. Save. This makes code
scanning findings block PRs; the thresholds shown in your screenshot alone do not
enforce merging. Keep the existing `contribution-guard` requirement too.

GitHub's [documented dependency graph formats](https://docs.github.com/en/code-security/reference/supply-chain-security/dependency-graph-supported-package-ecosystems)
do not include `uv.lock`. An enabled graph therefore does not prove complete Python
coverage. `uv audit --locked` in Contribution Guard checks locked direct,
transitive and development packages on PRs, manual runs and daily. Renovate's OSV
updates cover direct dependencies; a transitive audit finding needs a lockfile
update and a passing guard. To investigate locally:

```sh
uv audit --locked
```

For an affected transitive package, run `uv lock --upgrade-package PACKAGE_NAME`
using the package named by the audit, then rerun the audit and full gate. If an
exact direct pin prevents resolution, update that declaration through `uv add`
(use `--dev` for a development dependency). Review the resulting version and
lockfile changes. Do not add vulnerability ignores to make checks pass.

The CodeQL steps follow GitHub's [default setup instructions](https://docs.github.com/en/code-security/how-tos/find-and-fix-code-vulnerabilities/configure-code-scanning/configure-code-scanning).
The installed uv supports [dependency auditing](https://docs.astral.sh/uv/reference/cli/#uv-audit);
its experimental-feature notice is informational.

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

All label definitions live in
`.github/labels.json`. Manage changes through `scripts/sync_labels.py`; do not
create a second label workflow or edit label definitions only in GitHub.

Install the official GitHub CLI if needed. In Windows PowerShell:

```powershell
winget install --id GitHub.cli --exact --source winget
```

Open a new terminal, enter the OvertureDB checkout, and authenticate with an
account that can manage its labels:

```sh
gh auth login --hostname github.com --web
```

Preview, apply, then verify (each command is separate):

```sh
uv run --no-active --locked python scripts/sync_labels.py
```

```sh
uv run --no-active --locked python scripts/sync_labels.py --apply
```

```sh
uv run --no-active --locked python scripts/sync_labels.py --check
```

Expect 12 canonical labels, including `security`. If `github_actions` still exists
when you run the script, it automatically merges
`github_actions` into `ci` across **all open and closed issues and PRs**, then
deletes the old label only after every assignment succeeds. Retrying is safe.
The latest live label list already has the desired 12 labels, so no migration
should be needed. The removed historical/generic labels are not recreated.

Unexpected labels cause failure before any writes. Add each to the manifest as a
definition, or as an alias of the appropriate canonical label, then rerun. This
prevents silent drift and accidental removal of historical meaning. `--check`
exits nonzero for drift; a successful final check prints `Labels match labels.json.`

## Runner and action updates

Renovate's [GitHub Actions manager](https://docs.renovatebot.com/modules/manager/github-actions/)
supports literal `runs-on` versions through the `github-runners` datasource. The
configuration explicitly enables it, groups runner updates and requires manual
merge for OS upgrades. The runner datasource has no release timestamps, so its
rule clears the general minimum-release-age requirement to avoid stalled PRs.
Every action SHA has a matching version comment so
Renovate can update it. Python remains selected by `.python-version`; setup-uv
only selects the pinned uv version, with no unsupported `python-version-file` input.

GitHub refreshes the contents of its hosted runner images; `ubuntu-24.04` pins
the OS release, not an immutable old VM. Renovate proposes supported release
upgrades, but someone must review and merge them. No updater guarantees that a
runner can never become outdated. After merging this configuration, open
Renovate's **Dependency Dashboard**, expand **Detected dependencies**, and verify
`ubuntu-24.04` and all action references appear under GitHub Actions. Resolve any
Renovate configuration errors before considering updates operational.

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
