"""Keep workflow permissions, pins, checks and label references consistent."""

lazy import json
lazy import re
lazy from pathlib import Path

lazy import pytest
lazy import yaml

lazy from scripts.sync_labels import load_labels

ROOT = Path(__file__).resolve().parents[1]


def test_dataset_only_changes_never_start_analysis(subtests: pytest.Subtests) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    # PyYAML reads the bare `on` key as True.
    triggers = workflow[True]
    for event in ("push", "pull_request"):
        with subtests.test(event=event):
            assert triggers[event]["paths-ignore"] == ["data/**"]


def test_analysis_failures_use_native_job_status() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
    assert set(workflow["jobs"]) == {"codeql"}
    job = workflow["jobs"]["codeql"]
    assert "if" not in job
    for step in job["steps"]:
        assert not step.get("continue-on-error", False)
        assert "if" not in step
        if "github/codeql-action/init@" in step.get("uses", ""):
            assert step["with"]["languages"] == "python, actions"


def test_health_runs_on_schedule_and_manual_dispatch_only() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/dataset-health.yml").read_text()
    )
    triggers = workflow[True]
    assert set(triggers) == {"schedule", "workflow_dispatch"}
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
                        assert re.search(r"^\d+\.\d+\.\d+$", step["with"]["version"])
                        # uv reads Python's version from .python-version.
                        assert set(step["with"]) == {"version"}
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
    from scripts.queue_issues import KINDS

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
    for name in ("contribution-guard", "import-themerrdb", "publish-catalog"):
        content = (ROOT / f".github/workflows/{name}.yml").read_text()
        assert "bash scripts/pre-commit-check.sh" in content


def test_privileged_queue_runs_only_main_and_never_executes_pr_artifacts() -> None:
    source = (ROOT / ".github/workflows/contribution-queue.yml").read_text()
    workflow = yaml.safe_load(source)
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow[True]["schedule"][0]["cron"] == "*/5 * * * *"
    job = workflow["jobs"]["reconcile"]
    assert "DATASET_QUEUE_ENABLED == 'true'" in job["if"]
    assert job["steps"][0]["with"]["ref"] == "main"
    assert "DATASET_QUEUE_PUBLISH" in source
    assert "head_sha" not in source
    assert "download-artifact" not in source
    assert "pull_request_target" not in source
    assert "permission-pull-requests: write" in source
    assert "permission-workflows" not in source
    for path in (ROOT / "scripts").glob("*.py"):
        assert "HEAD:main" not in path.read_text()
        assert "commit_to_main" not in path.read_text()
    assert not (ROOT / ".github/workflows/contribution-command.yml").exists()
    health = (ROOT / ".github/workflows/dataset-health.yml").read_text()
    assert "permission-pull-requests" not in health


def test_import_workflow_cannot_publish_or_run_scheduled_direct_writes() -> None:
    source = (ROOT / ".github/workflows/import-themerrdb.yml").read_text()
    workflow = yaml.safe_load(source)
    assert set(workflow[True]) == {"workflow_dispatch"}
    assert "ARGS+=(--dry-run)" in source
    assert "create-github-app-token" not in source
