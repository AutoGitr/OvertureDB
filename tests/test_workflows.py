"""Keep workflow permissions, pins, checks and label references consistent."""

lazy import json
lazy import re
lazy import tomllib
lazy from pathlib import Path

lazy import pytest
lazy import yaml

lazy from scripts.automation import KINDS
lazy from scripts.sync_labels import load_labels

ROOT = Path(__file__).resolve().parents[1]


def test_python_requirement_matches_the_pinned_runtime() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    python = (ROOT / ".python-version").read_text().strip()
    assert project["project"]["requires-python"] == f"=={python}"


NONE: frozenset[str] = frozenset()
_LANGUAGE_FILTER = re.compile(
    r"grep -Eq '([^']+)' <<< \"\$changed\"; then\s+languages\+=\('\"([\w-]+)\"'\)"
)


@pytest.mark.parametrize(
    ("path", "languages"),
    [
        ("data/movies/603.json", NONE),
        ("schema/entry.schema.json", NONE),
        ("tests/test_catalog.py", NONE),
        (".github/README.md", NONE),
        ("scripts/catalog.py", frozenset({"python"})),
        ("schema/contract.py", frozenset({"python"})),
        (".github/workflows/contributions.yml", frozenset({"actions"})),
    ],
)
def test_codeql_analyses_only_the_languages_a_change_touches(
    path: str, languages: frozenset[str]
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    script = workflow["jobs"]["languages"]["steps"][1]["run"]
    filters = _LANGUAGE_FILTER.findall(script)
    assert {name for pattern, name in filters if re.search(pattern, path)} == languages
    assert """all='["python","actions"]'""" in script


def test_analysis_failures_use_native_job_status() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    assert set(workflow["jobs"]) == {"languages", "codeql"}
    job = workflow["jobs"]["codeql"]
    assert job["if"] == "needs.languages.outputs.languages != '[]'"
    for step in job["steps"]:
        assert not step.get("continue-on-error", False)
        assert "if" not in step


def _triggers(name: str) -> dict[str, object]:
    workflow = yaml.safe_load((ROOT / f".github/workflows/{name}").read_text())
    # PyYAML reads the bare `on` key as True.
    return workflow[True]


def test_the_daily_pipeline_starts_with_the_import() -> None:
    assert set(_triggers("import-themerrdb.yml")) == {"schedule", "workflow_dispatch"}
    for name in ("dataset-health.yml", "publish-catalog.yml"):
        triggers = _triggers(name)
        assert set(triggers) == {"workflow_run", "workflow_dispatch"}, name
        assert triggers["workflow_run"] == {
            "workflows": ["Import ThemerrDB"],
            "types": ["completed"],
        }, name


def test_every_daily_run_validates_builds_and_deploys_the_catalog() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/publish-catalog.yml").read_text()
    )
    assert "if" not in workflow["jobs"]["deploy"]
    for step in workflow["jobs"]["build"]["steps"]:
        assert "if" not in step


def test_health_steps_behave_the_same_for_every_trigger() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/dataset-health.yml").read_text()
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
            assert "permissions" in workflow
            for action in re.findall(r"(?m)^\s*-?\s*uses: (.+)$", path.read_text()):
                assert re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", action)
            for job in workflow["jobs"].values():
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
                        assert "with" not in step
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
    renovate = json.loads((ROOT / ".github" / "renovate.json").read_text())
    assert set(renovate["labels"]) <= names
    assert set(renovate["vulnerabilityAlerts"]["labels"]) <= names
    for rule in renovate["packageRules"]:
        assert set(rule.get("addLabels", [])) <= names


def test_contribution_kind_labels_are_managed() -> None:
    assert {label["name"] for label in load_labels()} >= KINDS


def test_runner_updates_are_enabled_without_automatic_os_upgrades() -> None:
    renovate = json.loads((ROOT / ".github" / "renovate.json").read_text())
    rule = next(
        rule
        for rule in renovate["packageRules"]
        if "github-runners" in rule.get("matchDatasources", [])
    )
    assert rule["enabled"] is True
    assert rule["automerge"] is False
    # Runner releases have no timestamps, so an age requirement blocks updates.
    assert rule["minimumReleaseAge"] is None


def test_all_validation_jobs_use_the_same_gate() -> None:
    guard = (ROOT / ".github/workflows/contribution-guard.yml").read_text()
    assert "bash scripts/contribution-check.sh" in guard
    checks = (ROOT / "scripts/contribution-check.sh").read_text()
    assert "bash scripts/pre-commit-check.sh" in checks
    assert "uv audit --locked" in checks
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
        "group": "dataset-write",
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
        "dataset-health.yml",
        "import-themerrdb.yml",
        "publish-catalog.yml",
    }
    health = (ROOT / ".github/workflows/dataset-health.yml").read_text()
    assert "permission-pull-requests" not in health


def test_import_workflow_runs_on_main_with_dataset_write_concurrency() -> None:
    source = (ROOT / ".github/workflows/import-themerrdb.yml").read_text()
    workflow = yaml.safe_load(source)
    assert workflow["concurrency"] == {
        "group": "dataset-write",
        "cancel-in-progress": False,
        "queue": "max",
    }
    assert set(workflow[True]) == {"schedule", "workflow_dispatch"}
    job = workflow["jobs"]["import"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert "ARGS+=(--commit)" in source
    assert "aquasecurity/setup-trivy@" in source
