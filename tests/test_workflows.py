"""Keep workflow permissions, pins, checks and label references consistent."""

lazy import json
lazy import re
lazy import tomllib
lazy from pathlib import Path, PurePosixPath

lazy import pytest
lazy import yaml

lazy from schema.contract import (
    ISSUE_FORM_FIELDS,
    ISSUE_FORMS,
    OPTIONAL_ENTRY_FIELDS,
    entry_fields,
)
lazy from scripts.automation import KINDS, TITLE_KINDS
lazy from scripts.sync_labels import load_labels

ROOT = Path(__file__).resolve().parents[1]


def test_python_requirement_matches_the_pinned_runtime() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    python = (ROOT / ".python-version").read_text().strip()
    assert project["project"]["requires-python"] == f"=={python}"


def _filtered_in(path: str, patterns: list[str]) -> bool:
    """Whether a change to *path* starts a run, as GitHub reads ``paths``.

    The last pattern a path matches decides, and a ``!`` pattern excludes it.
    """
    included = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        if PurePosixPath(path).full_match(pattern.removeprefix("!")):
            included = not negated
    return included


@pytest.mark.parametrize(
    ("path", "analysed"),
    [
        ("data/movies/603.json", False),
        ("schema/entry.schema.json", False),
        ("tests/test_catalog.py", False),
        (".github/README.md", False),
        ("scripts/catalog.py", True),
        ("schema/contract.py", True),
        (".github/workflows/contributions.yml", True),
        (".github/codeql/codeql-config.yml", True),
    ],
)
def test_codeql_runs_for_analysed_code_and_then_analyses_every_language(
    path: str, *, analysed: bool
) -> None:
    """Every run analyses every language, so code scanning compares it with main's."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    # PyYAML reads the bare `on` key as True.
    patterns = workflow[True]["pull_request"]["paths"]
    assert workflow[True]["push"]["paths"] == patterns
    assert _filtered_in(path, patterns) is analysed
    assert set(workflow["jobs"]["codeql"]["strategy"]["matrix"]["language"]) == {
        "python",
        "actions",
    }


def test_analysis_failures_use_native_job_status() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    assert set(workflow["jobs"]) == {"codeql"}
    job = workflow["jobs"]["codeql"]
    assert "if" not in job
    for step in job["steps"]:
        assert not step.get("continue-on-error", False)
        assert "if" not in step


def _triggers(name: str) -> dict[str, object]:
    workflow = yaml.safe_load((ROOT / f".github/workflows/{name}").read_text())
    # PyYAML reads the bare `on` key as True.
    return workflow[True]


def test_the_daily_pipeline_starts_with_the_import_which_calls_the_rest() -> None:
    assert set(_triggers("import-themerrdb.yml")) == {"schedule", "workflow_dispatch"}
    # Called, never woken by another workflow's run, which a fork could start.
    for name in ("catalog-health.yml", "publish-catalog.yml"):
        assert set(_triggers(name)) == {"workflow_call", "workflow_dispatch"}, name
    jobs = yaml.safe_load(
        (ROOT / ".github/workflows/import-themerrdb.yml").read_text()
    )["jobs"]
    assert jobs["health"]["uses"] == "./.github/workflows/catalog-health.yml"
    assert jobs["publish"]["uses"] == "./.github/workflows/publish-catalog.yml"
    # The day's contributions go out whatever the import did.
    assert jobs["health"]["if"] == jobs["publish"]["if"] == "${{ !cancelled() }}"


def test_each_job_names_its_permissions_in_one_place() -> None:
    # The repository's default token reads only; each job says what it needs.
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text())
        assert "permissions" not in workflow, path.name
        for name, job in workflow["jobs"].items():
            assert "permissions" in job, f"{path.name}: {name}"


def test_every_daily_run_validates_builds_and_deploys_the_catalog() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/publish-catalog.yml").read_text()
    )
    assert "if" not in workflow["jobs"]["deploy"]
    for step in workflow["jobs"]["build"]["steps"]:
        assert "if" not in step


def test_health_steps_behave_the_same_for_every_trigger() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/catalog-health.yml").read_text()
    )
    step = workflow["jobs"]["health"]["steps"][-1]
    assert "EVENT_NAME" not in step["env"]


def test_guard_checkout_fetches_full_history_for_pr_diffs() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/contribution-guard.yml").read_text()
    )
    checkout = workflow["jobs"]["contribution-guard"]["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0


def test_workflows_pin_actions_bound_runtime_and_do_not_persist_credentials(
    subtests: pytest.Subtests,
) -> None:
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        with subtests.test(path=path.name):
            for action in re.findall(r"(?m)^\s*-?\s*uses: (.+)$", path.read_text()):
                # The repository's own workflows are called at this commit.
                if action.startswith("./.github/workflows/"):
                    continue
                assert re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", action)
            for job in workflow["jobs"].values():
                if "uses" in job:
                    continue
                assert "${{ matrix." not in job.get("name", "")
                assert re.search(r"^ubuntu-\d{2}\.04$", job["runs-on"])
                assert job["timeout-minutes"] <= 20
                for step in job["steps"]:
                    if "uses" in step:
                        assert re.search(
                            r"^[\w-]+/[\w-]+(?:/[\w.-]+)*@[0-9a-f]{40}$", step["uses"]
                        )
                    if step.get("uses", "").startswith("actions/checkout@"):
                        assert step["with"]["persist-credentials"] is False
                    if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                        # setup-uv installs the required-version from
                        # pyproject.toml, and uv reads Python's version from
                        # .python-version.
                        assert step.get("with", {}) in (
                            {},
                            {"working-directory": "overture-checkout"},
                        )
                    run = step.get("run", "")
                    assert "${{" not in run, (
                        "Pass expressions through env, not shell interpolation"
                    )
                    assert not re.search(r"uv run (?!\-\-locked)", run)


def test_form_and_renovate_labels_exist_in_manifest() -> None:
    labels = load_labels()
    names = {label["name"] for label in labels}
    assert len(names) == len(labels)
    for label in labels:
        assert re.fullmatch(r"[0-9a-f]{6}", label["color"])
        assert label["description"]
    for path in (ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"):
        form = yaml.safe_load(path.read_text())
        assert set(form.get("labels", [])) <= names
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        source = path.read_text()
        referenced = set(re.findall(r"labels\.\*\.name,\s*'([^']+)'", source))
        for group in re.findall(
            r"fromJSON\('(\[[^']+])'\), github.event.label.name", source
        ):
            referenced.update(json.loads(group))
        assert referenced <= names
    shared = ROOT.parent / "Overture/.github/renovate-shared.json"
    if shared.is_file():
        renovate = json.loads(shared.read_text())
        assert set(renovate["labels"]) <= names
        assert set(renovate["vulnerabilityAlerts"]["labels"]) <= names
        for rule in renovate["packageRules"]:
            assert set(rule.get("addLabels", [])) <= names


def test_contribution_kind_labels_are_managed() -> None:
    assert {label["name"] for label in load_labels()} >= KINDS


def test_every_contribution_form_title_names_its_kind_label() -> None:
    forms = {}
    for path in (ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"):
        form = yaml.safe_load(path.read_text())
        if kinds := set(form.get("labels", [])) & KINDS:
            forms[form["title"].split(" ", 1)[0]] = kinds.pop()
    assert forms == TITLE_KINDS
    gate = yaml.safe_load((ROOT / ".github/workflows/contributions.yml").read_text())[
        "jobs"
    ]["process"]["if"]
    for prefix in TITLE_KINDS:
        assert f"startsWith(github.event.issue.title, '{prefix}')" in gate


def test_renovate_rules_are_overtures_shared_preset() -> None:
    """Overture tests the preset; a dependency both use updates alike in each."""
    renovate = json.loads((ROOT / ".github" / "renovate.json").read_text())
    assert renovate["extends"] == ["github>AutoGitr/Overture//.github/renovate-shared"]
    assert set(renovate) <= {"$schema", "description", "extends"}


def test_all_validation_jobs_use_the_same_gate() -> None:
    guard = (ROOT / ".github/workflows/contribution-guard.yml").read_text()
    assert "bash scripts/contribution-check.sh" in guard
    checks = (ROOT / "scripts/contribution-check.sh").read_text()
    assert "bash scripts/pre-commit-check.sh" in checks
    assert "uv audit --locked --preview-features audit-command" in checks
    assert "trivy fs --scanners secret --exit-code 1 ." in checks
    for name in ("contributions", "import-themerrdb", "contribution-guard"):
        source = (ROOT / f".github/workflows/{name}.yml").read_text()
        assert "aquasecurity/setup-trivy@" in source


def test_privileged_contributions_run_only_main_and_never_execute_pr_artifacts() -> (
    None
):
    source = (ROOT / ".github/workflows/contributions.yml").read_text()
    workflow = yaml.safe_load(source)
    assert workflow["concurrency"] == {
        "group": "catalog-write",
        "cancel-in-progress": False,
        "queue": "max",
    }
    assert set(workflow[True]) == {"issues", "issue_comment", "workflow_dispatch"}
    job = workflow["jobs"]["process"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert job["steps"][0]["with"]["ref"] == "main"
    assert "head_sha" not in source
    assert "download-artifact" not in source
    assert "pull_request_target" not in source
    assert "permission-pull-requests" not in source
    assert "permission-workflows" not in source
    assert {p.name for p in (ROOT / ".github/workflows").glob("*.yml")} == {
        "codeql.yml",
        "contribution-guard.yml",
        "contributions.yml",
        "catalog-health.yml",
        "docs.yml",
        "import-themerrdb.yml",
        "publish-catalog.yml",
    }
    health = (ROOT / ".github/workflows/catalog-health.yml").read_text()
    assert "permission-pull-requests" not in health


def test_import_workflow_runs_on_main_with_catalog_write_concurrency() -> None:
    source = (ROOT / ".github/workflows/import-themerrdb.yml").read_text()
    workflow = yaml.safe_load(source)
    assert workflow["concurrency"] == {
        "group": "catalog-write",
        "cancel-in-progress": False,
        "queue": "max",
    }
    assert set(workflow[True]) == {"schedule", "workflow_dispatch"}
    job = workflow["jobs"]["import"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert set(workflow[True]["workflow_dispatch"]["inputs"]) == {"limit"}
    assert "aquasecurity/setup-trivy@" in source


def test_issue_forms_have_the_fields_the_contract_fills() -> None:
    for media_type, name in ISSUE_FORMS.items():
        form = yaml.safe_load((ROOT / ".github/ISSUE_TEMPLATE" / name).read_text())
        ids = [field["id"] for field in form["body"] if "id" in field]
        filled = {
            ISSUE_FORM_FIELDS[field]
            for field in (*entry_fields(media_type), *OPTIONAL_ENTRY_FIELDS[media_type])
            if field in ISSUE_FORM_FIELDS
        }
        assert filled <= set(ids), (name, filled - set(ids))
        assert [field_id for field_id in ids if field_id in filled] == [
            form_id for form_id in ISSUE_FORM_FIELDS.values() if form_id in filled
        ], name
        assert media_type in form["labels"]


def test_the_contributor_guide_lives_only_in_the_docs() -> None:
    """GitHub's file points at the docs pages, so the guide is written once."""
    pointer = (ROOT / ".github/CONTRIBUTING.md").read_text()
    assert "/overturedb/contributing" in pointer
    assert pointer.count("\n") < 12
    assert (ROOT / "docs/contributing/index.md").is_file()
