# Contributing to OvertureDB

<details>
<summary><b>Selection guidelines</b></summary>

## Selection guidelines

OvertureDB stores verified metadata, direct image links, and YouTube theme IDs.

### General rules

- **Preferred Source**: TMDB is the preferred and prioritised artwork source. TPDb is good for franchise and collection artwork sets.
- **Resolution**: The higher the better, as long as it doesn't compromise other criteria. Posters and season posters should be at least 1000x1500 and backgrounds at least 1600x900.
- **Aspect Ratio Margin (1% Rule)**: The aspect ratio of submitted artwork must lie within a 1% margin of the target aspect ratio:
  - Posters and season posters (2:3 target ratio = 0.667): allowed ratio range is 0.660 to 0.674 (for example, 2000x3000).
  - Backgrounds (16:9 target ratio = 1.778): allowed ratio range is 1.760 to 1.796 (for example, 3840x2160 or 1920x1080).
- **Represent the Item**: The artwork and theme should match the tone, genre, and aesthetic of the movie or show (to some degree).
- **Visual Consistency**: Keep artwork consistent across a franchise, collection or a show's seasons. When you pick artwork from a poster set, such as one of the [example poster sets](#example-poster-sets), aim to contribute that set's artwork for every item it covers.
- **Criterion Collection Films**: Any Criterion film must use a properly formatted Criterion poster. It must use modern Criterion formatting (clean layout), correct aspect ratio (not stretched or distorted), and authentic Criterion cover art.
- **Exceptions**: Can be made to any of the rules above when a good reason is given or in special cases.
- **No Spoilers or Explicit/Malicious Content**: Submissions must not contain spoilers to major plot points, adult or explicit (NSFW) imagery, nudity, gore, or deceptive/malicious links.

### Artwork requirements

#### Posters

- Must contain the title.
- Preferably no other text unless it suits the item.

#### Backgrounds

- Must be a real scene or shot taken directly from the item.
- No text unless it naturally appears in the scene.
- Never use "photoshopped" composite images where main characters are cut out and placed together, or shown as floating heads.

#### Season posters

- Must contain the show's title and season title/info ("Season 1").
- Preferably no other text unless it suits the item.
- A show's season posters must be consistent with each other.

### Theme requirements

- Preferred length is 1 to 2 minutes.
- Music should begin immediately without leading silence or prolonged fade-ins.
- Clean audio only: no dialogue intros, YouTube outro promotions, watermarks, or abrupt cutoffs.
- OvertureDB imports ThemerrDB's themes daily. Contributions only set `youtube_id_overturedb`; review links compare that field alone. A contributed theme must differ from the item's imported `youtube_id_themerrdb`, so each item has a fallback when a video is removed or region-restricted. Matching imported themes are omitted from contributions. Bulk exports cannot set or replace the imported theme, and their `youtube_id_themerrdb` values are ignored.

### Allowed sources and URL formats

| Source | Priority | Stored Link | Also Accepted (automatically converted on submission) |
| :--- | :--- | :--- | :--- |
| **TMDB** | Primary & Preferred | `https://image.tmdb.org/t/p/original/<file>` | Any other size (`w342`, `w780`, ...) and `themoviedb.org` image links. |
| **ThePosterDB** | Secondary | `https://theposterdb.com/api/assets/<id>` | Poster pages (`/poster/<id>`), `/view` links and `www.theposterdb.com`. |
| **Fanart.tv** | Secondary | `https://assets.fanart.tv/fanart/<path>` | `/preview/` thumbnails and `fanart.tv` links. |
| **TheTVDB** | Secondary | `https://artworks.thetvdb.com/banners/<path>` | `_t` thumbnails, `_cache/` links and `thetvdb.com` links. |
| **Plex Static** | Secondary | `https://metadata-static.plex.tv/<path>` | |

- Every entry stores the full-size original over HTTPS, without query strings or fragments. Submitted links are converted to that form; links on these hosts that do not name an image (sets, pages, viewers) are rejected.
- Images must be JPEG (`.jpg`, `.jpeg`) or PNG (`.png`) files.
- The rules live in `schema/contract.py`, which Overture uses too.

### Example poster sets

| Series / Category | Poster Set Link | Notes |
| :--- | :--- | :--- |
| **Apocalypse Documentaries** | https://theposterdb.com/set/398222 | Documentary series. |
| **David Attenborough Documentaries** | https://theposterdb.com/set/125988 | From TPDB user `fwlolx`. |
| **Disneynature** | https://theposterdb.com/set/11090 | |
| **James Bond** | https://theposterdb.com/set/62004 | |
| **Ken Burns Documentaries** | https://theposterdb.com/poster/218606 | Images in this format from TPDB user `fwlolx`. |
| **Marvel Cinematic Universe** | https://theposterdb.com/set/87082 | |
| **Pixar Animation Studios** | https://theposterdb.com/set/97 | |
| **Pixar Shorts** | https://theposterdb.com/set/11456 | |
| **Planet Documentaries** | https://theposterdb.com/set/143160 | Use for the planet series (*Planet Earth*, *Blue Planet*, etc.). |
| **Studio Ghibli** | https://theposterdb.com/set/32965 | |
| **Walt Disney Animation Studios** | https://theposterdb.com/set/2454 | |
| **Walt Disney Animation Studios Shorts** | https://theposterdb.com/poster/206944 | Images in this format from TPDB users `scoobymcsnack`, `DIIIVOY`, and `HammerActually`. |

### How to submit

#### With Overture (recommended)

[Overture](https://github.com/AutoGitr/Overture) finds gaps in the catalog, checks candidates and prepares submissions; use the guidelines above to judge visual consistency, suitability, and theme quality.

- **Find missing selections**: Filter for incomplete OvertureDB items to see where contributions are needed.
- **Workflow & auto-advance**: Enable auto-advance in settings to move from poster to background to theme to the next item as you make selections.
- **Aspect ratio limits**: Verifies pixel dimensions against the 1% rule (2:3 for posters, 16:9 for backgrounds).
- **Known resolutions & sorting**: Detects exact dimensions and sorts candidates by resolution, highest first.
- **True image validation**: Checks image file headers for authentic JPEG and PNG files.
- **Direct links**: Converts every artwork link to the full-size original form the catalog stores.
- **Accurate external IDs**: Pairs TMDB, TVDB, and IMDb IDs from your media server match.
- **Prefilled submissions**: The GitHub contribution link opens the issue form with title, year, external IDs, URLs and replaced values filled in.

Review the details and click **Submit new issue**. To contribute all your selections at once, export them (**OvertureDB -> Export selections**) and attach the `.zip` to the [bulk contribution](https://github.com/AutoGitr/OvertureDB/issues/new?template=bulk.yml) form.

#### Manually

- **[Movie](https://github.com/AutoGitr/OvertureDB/issues/new?template=movie.yml)**: Title, year, external IDs, poster URL, background URL, and YouTube ID.
- **[Show](https://github.com/AutoGitr/OvertureDB/issues/new?template=show.yml)**: Same as movie, plus season poster URLs (`season_number=url`).

#### Changing an existing entry

Use the movie or show form. To replace an identifier, artwork or theme, or to remove the entry, explain why in "Reason for modification" (such as a wrong TMDB ID, higher resolution, or a dead link).

A preview comment shows validation results, the selections and the diff. A maintainer then approves or rejects the submission.

</details>

<details>
<summary><b>Development and maintenance</b></summary>

## Review

Use `movie`, `show`, or `bulk`.
Preview comments show validation failures, clickable selections and the proposed
diff. Single-entry submissions are rejected for unreachable artwork, new artwork
outside the 1% rule, or a new theme that is removed or private on YouTube, and
warn about new artwork below the recommended resolution. Bulk archives are not
fetched; Dataset Health reports the same findings for them. Replacing a value
or removing an entry requires a reason. Bulk archives add
missing values and keep imported ThemerrDB themes. Invalid bulk records block
the whole contribution; fix the archive before review. Limits are 10 MB
downloaded, 100,000 JSON entries, 1 MB per entry, and 50 MB of uncompressed
JSON. These are archive safety limits. Review size is based on the final changed
entries, excluding unchanged records and consolidating repeated records for the
same entry. A large export with few changes can fit; a large set of actual changes
must still be split so every change can be reviewed. Validation errors are reported
before preview-size errors.

A collaborator with write, maintain or admin permission can comment:

```text
@OvertureDB-bot approve
```

```text
@OvertureDB-bot reject
```

Append a reason to the reject command on the same line when useful. Maintainers
can edit the issue description to adjust URLs or metadata before approving.

Approval re-evaluates the contribution against `main`, verifies that the previewed
changes have not been altered or superseded by a conflicting update, and applies
the proposed changes in an isolated checkout. The complete Contribution Guard
(tests, coverage, lint, types, dataset validation, dependency audit and secret scan)
must pass before a GitHub-signed commit is created on `main` and the issue closes.
ThemerrDB imports use this same gate. Failed checks publish nothing.
If `main` advances during validation, dataset changes are rebuilt and rechecked
up to three times. Code changes require a fresh workflow run. Publication is pinned
to the validated base revision; an API failure is never blindly retried.
Unrelated commits to `main`
and changes to untouched fields on a single-entry contribution do not invalidate
the preview. Bulk approvals are bound to the complete planned files; a change to
any affected file requires another review.
If the issue was edited or a reviewed field changed on `main` since the preview
was posted, the bot refreshes the preview comment and requests a new approval.
Keep the approval comment unchanged until processing finishes. Closing or editing
the issue, deleting the approval, or losing write permission stops pending approval.
If a commit fails, the bot leaves the issue open with recovery instructions.
Maintainers can also refresh an issue from the Contributions workflow's **Run
workflow** action by entering its issue number. Large previews must be split into
smaller contributions so every change fits in the review comment.

## Development

Use the pinned Python and uv versions. Python is pinned exactly in
`requires-python` and `.python-version`; update both together with `uv.lock`,
including for patch releases. Renovate's pinning policy is intentional.
The same read-only gate runs locally and in CI:

```sh
uv sync --locked
```

```sh
bash scripts/pre-commit-check.sh
```

It checks the lockfile, Ruff lint/formatting, strict Pyright types, the pytest
suite with branch coverage, workflow invariants, and every dataset
entry. On Windows, run it in Git Bash.
To run it on every commit, enable the Git hooks once per clone with
`git config core.hooksPath .githooks`.
To format changes, use `uv run --locked ruff format scripts schema tests`.

PR checks and a weekly scheduled guard also run `uv audit --locked`, covering
direct, transitive and development dependencies. Run it locally when changing
dependencies; it requires network access and currently emits uv's experimental
feature notice. No vulnerabilities are ignored.

### Lint and type exceptions

Production scripts and tests both pass strict Pyright. Ruff detects unused
`noqa` comments, and Pyright rejects unnecessary type-ignore comments. No test
file is excluded; tests allow `S101` because pytest checks plain assertions. CLI
entry points allow `T201` because printing results/errors is their interface.

The remaining inline exceptions are deliberate and documented at their call sites:
`S603` for fixed executables with argument arrays and no shell; `S310` for HTTPS
requests checked against allowed hosts and public addresses, including redirects;
and `S314` for parsing locally generated SVG in tests. The two narrow Pyright
exceptions in `schema/contract.py` cover incomplete upstream jsonschema factory
and validation stubs. They do not suppress data validation or other diagnostics.

Optional network checks and publication from a clean checkout:

```sh
uv run --locked python -m scripts.catalog validate --check-urls --entry data/movies/tmdb-123.json
```

```sh
uv run --locked python -m scripts.catalog build
```

The build produces the JSON Lines catalog (a header line, then one entry per
line; plain and gzip), schemas, licenses, checksums, and statistics in
`public/`. Its revision and timestamp come from the source commit. Tests verify
reproducibility without requiring a clean working tree.

The workflows keep triggers, permissions and token creation in YAML. Tested
Python scripts own validation, review formatting and publication; `scripts`
and `schema` are packages, so run every script from the repository root as
`python -m scripts.<name>`. `scripts/github.py` names the bot and makes every
GitHub API call and push. Every script reads and writes entries through
`scripts/catalog.py`: `EntryIndex` finds an entry by any of its identifiers,
`new_entry` builds one with every field, `merge_ids` adds identifiers and
refuses conflicting ones, `ENTRY_FILE` matches entry file paths,
and `entry_path`, `planned_file_changes` and `write_changes` decide where and
how an entry is written.
Rules on entry values (ID patterns, title length, year range, the TMDB, TVDB,
IMDb identifier preference that names entry files) come from `schema/contract.py`.
Only the workflows push.

## Workflows and repository settings

| Workflow | Purpose |
| --- | --- |
| Contributions | Validate contribution issues, post preview comments, and commit approved changes to `main`. |
| Contribution Guard | Run the full checks and dependency audit on PRs and pushes to `main`, and block non-maintainer dataset PRs. |
| CodeQL | Scan Python and Actions code when it changes, and both weekly; dataset contributions start no analysis. |
| Import ThemerrDB | Import new and updated ThemerrDB themes daily, starting the daily pipeline (or on manual dispatch with optional dry-run). |
| Dataset Health | Check entries after each import and update the `health` issue. |
| Publish Catalog | After each import, validate, build and deploy the catalog to Pages in one deploy for the day. A manual run publishes at once. |

Dataset Health checks 200 entries per daily run, new and changed ones first:
artwork reachability, the 1% rule and theme availability as problems, and
artwork below the recommended resolution as warnings, each in its own section of
the `health` issue. Every run also rechecks all entries with reported findings
whose content has changed since
their last completed check, outside that limit. Changes older than 24 hours are
included too, so a missed run cannot leave a fix behind. Transient failures keep
the previous findings and are retried on a later run. Its state lives on the
`state/health` branch.

Keep `contribution-guard` required on `main`, with GitHub Actions as its source,
with strict up-to-date checks and signed commits. Grant the OvertureDB GitHub App
bypass permission on the `main` and `state/*` branch rulesets so it can commit
approved dataset contributions and update `state/health`. The app's direct writes
are gated by `scripts/publication.py` and the shared `scripts/contribution-check.sh`;
the post-push status alone does not enforce validation before publication.
Do not require CodeQL
in branch rulesets.

Configure GitHub Pages to deploy with GitHub Actions. Install the OvertureDB
GitHub App on this repository and set `OVERTUREDB_CLIENT_ID` and
`OVERTUREDB_APP_PRIVATE_KEY`. The app needs contents and issues write access.
Protect `state/*` against other non-admin writers.
Workflow job permissions remain separate from that app token.

Repository labels are defined in `.github/labels.json`. Preview changes with
`uv run --locked python -m scripts.sync_labels`; use `--apply` to reconcile them
or `--check` to detect drift.

## Shared schema

Every file in `schema/` except the package's `__init__.py`
(`entry.schema.json`, `catalog.schema.json` and `contract.py`) is shared with
Overture, whose CI fails while its copy differs. After changing them, validate
existing data and run, from the sibling Overture checkout:

```sh
uv run python -m scripts.dataset_contract ../OvertureDB
```

Submit both repositories' changes together. Increment `SCHEMA_VERSION` for
breaking changes; do not introduce compatibility shims.

</details>

Report security vulnerabilities privately using [SECURITY.md](SECURITY.md).
