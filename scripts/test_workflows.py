"""Keep workflow permissions, pins, checks and label references consistent."""

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from sync_labels import load_labels

ROOT = Path(__file__).resolve().parents[1]


class CodeQLTests(unittest.TestCase):
    def run_script(
        self, job: str, env: dict[str, str], setup: str = ""
    ) -> tuple[subprocess.CompletedProcess[str], str]:
        bash = shutil.which("bash")
        if bash is None:
            self.skipTest("Bash is required to exercise workflow scripts")
        workflow = yaml.safe_load(
            (ROOT / ".github/workflows/codeql.yml").read_text(encoding="utf-8")
        )
        script = workflow["jobs"][job]["steps"][-1]["run"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            # Execute only checked-in workflow code and fixed test setup in an
            # isolated directory, using the resolved Bash executable.
            result = subprocess.run(  # noqa: S603
                [
                    bash,
                    "--noprofile",
                    "--norc",
                    "-e",
                    "-o",
                    "pipefail",
                    "-c",
                    setup + script,
                ],
                cwd=directory,
                env={**os.environ, **env, "GITHUB_OUTPUT": output.as_posix()},
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            return result, output.read_text() if output.exists() else ""

    def test_gate_only_accepts_successful_analysis_or_explicit_data_skip(self) -> None:
        for detect in ("success", "failure", "cancelled", "skipped"):
            for run in ("true", "false", ""):
                for analyze in ("success", "failure", "cancelled", "skipped"):
                    with self.subTest(detect=detect, run=run, analyze=analyze):
                        result, _ = self.run_script(
                            "codeql-gate",
                            {
                                "DETECT_RESULT": detect,
                                "RUN_CODEQL": run,
                                "ANALYZE_RESULT": analyze,
                            },
                        )
                        accepted = detect == "success" and (run, analyze) in {
                            ("true", "success"),
                            ("false", "skipped"),
                        }
                        self.assertEqual(
                            result.returncode == 0, accepted, result.stdout
                        )

    def test_change_detection_fails_when_git_diff_fails(self) -> None:
        result, output = self.run_script(
            "detect-changes",
            {
                "EVENT_NAME": "pull_request",
                "BASE_SHA": "missing",
                "HEAD_SHA": "missing",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("run_codeql=false", output)

    def test_change_detection_handles_data_code_and_renames(self) -> None:
        setup = """
git init -q
git config user.name Test
git config user.email test@example.com
git config commit.gpgsign false
mkdir data
printf 'original\\n' > data/entry.json
printf 'code\\n' > script.py
git add .
git commit -qm base
BASE_SHA=$(git rev-parse HEAD)
"""
        for change, expected in (
            ("printf 'changed\\n' > data/entry.json", "false"),
            ("printf 'changed\\n' > script.py", "true"),
            ("git mv script.py data/script.py", "true"),
            ("git mv data/entry.json data/renamed.json", "false"),
        ):
            with self.subTest(change=change):
                result, output = self.run_script(
                    "detect-changes",
                    {"EVENT_NAME": "pull_request"},
                    setup + change + "\ngit add .\ngit commit -qm change\n"
                    "HEAD_SHA=$(git rev-parse HEAD)\n",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.strip(), f"run_codeql={expected}")

    def test_non_pr_events_always_run_analysis(self) -> None:
        for event in ("push", "schedule"):
            with self.subTest(event=event):
                result, output = self.run_script(
                    "detect-changes", {"EVENT_NAME": event}
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(output.strip(), "run_codeql=true")


class WorkflowTests(unittest.TestCase):
    def test_workflows_pin_actions_bound_runtime_and_do_not_persist_credentials(
        self,
    ) -> None:
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertIn("permissions", workflow)
                for action in re.findall(r"(?m)^\s*-?\s*uses: (.+)$", path.read_text()):
                    self.assertRegex(action, r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$")
                for job in workflow["jobs"].values():
                    self.assertRegex(job["runs-on"], r"^ubuntu-\d{2}\.04$")
                    self.assertLessEqual(job["timeout-minutes"], 20)
                    for step in job["steps"]:
                        if "uses" in step:
                            self.assertRegex(
                                step["uses"],
                                r"^[\w-]+/[\w-]+(?:/[\w.-]+)*@[0-9a-f]{40}$",
                            )
                        if step.get("uses", "").startswith("actions/checkout@"):
                            self.assertIs(step["with"]["persist-credentials"], False)
                        if step.get("uses", "").startswith("astral-sh/setup-uv@"):
                            self.assertRegex(
                                step["with"]["version"], r"^\d+\.\d+\.\d+$"
                            )
                            # uv reads Python's version from .python-version.
                            self.assertEqual(set(step["with"]), {"version"})
                        run = step.get("run", "")
                        self.assertNotIn(
                            "${{",
                            run,
                            "Pass expressions through env, not shell interpolation",
                        )
                        self.assertNotRegex(run, r"uv run (?!\-\-locked)")

    def test_form_and_renovate_labels_exist_in_manifest(self) -> None:
        labels = load_labels()
        names = {label["name"] for label in labels}
        self.assertEqual(len(names), len(labels))
        for label in labels:
            self.assertTrue(re.fullmatch(r"[0-9a-f]{6}", label["color"]))
            self.assertTrue(label["description"])
        for path in (ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"):
            form = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertTrue(set(form.get("labels", [])) <= names)
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            source = path.read_text(encoding="utf-8")
            referenced = set(re.findall(r"labels\.\*\.name,\s*'([^']+)'", source))
            for group in re.findall(
                r"fromJSON\('(\[[^']+])'\), github.event.label.name", source
            ):
                referenced.update(json.loads(group))
            self.assertTrue(referenced <= names, referenced - names)
        renovate = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
        self.assertTrue(set(renovate["labels"]) <= names)
        self.assertTrue(set(renovate["vulnerabilityAlerts"]["labels"]) <= names)
        for rule in renovate["packageRules"]:
            self.assertTrue(set(rule.get("addLabels", [])) <= names)

    def test_labels_emitted_by_automation_are_managed(self) -> None:
        names = {label["name"] for label in load_labels()}
        source = ast.parse((ROOT / "scripts/automation.py").read_text())
        emitted: set[str] = set()
        for node in ast.walk(source):
            candidates: list[ast.expr] = []
            if isinstance(node, ast.Dict):
                candidates = [
                    value
                    for key, value in zip(node.keys, node.values, strict=True)
                    if isinstance(key, ast.Constant) and key.value == "labels"
                ]
            elif isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "labels"
                for target in node.targets
            ):
                candidates = [node.value]
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "labels"
                and node.func.attr == "append"
            ):
                candidates = node.args
            for candidate in candidates:
                for child in ast.walk(candidate):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        emitted.add(child.value)
        self.assertTrue(emitted)
        self.assertTrue(emitted <= names, emitted - names)

    def test_runner_updates_are_enabled_without_automatic_os_upgrades(self) -> None:
        renovate = json.loads((ROOT / "renovate.json").read_text())
        rule = next(
            rule
            for rule in renovate["packageRules"]
            if "github-runners" in rule.get("matchDatasources", [])
        )
        self.assertIs(rule["enabled"], True)
        self.assertIs(rule["automerge"], False)
        # Runner releases have no timestamps, so an age requirement blocks updates.
        self.assertIsNone(rule["minimumReleaseAge"])

    def test_all_validation_jobs_use_the_same_gate(self) -> None:
        for name in ("contribution-guard", "import-themerrdb", "publish-catalog"):
            content = (ROOT / f".github/workflows/{name}.yml").read_text(
                encoding="utf-8"
            )
            self.assertIn("bash scripts/pre-commit-check.sh", content)
