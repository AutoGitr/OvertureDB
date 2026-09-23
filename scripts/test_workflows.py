"""Keep workflow permissions, pins, checks and label references consistent."""

import ast
import json
import re
import unittest
from pathlib import Path

import yaml
from sync_labels import load_labels

ROOT = Path(__file__).resolve().parents[1]


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
                                step["uses"], r"^[\w-]+/[\w-]+@[0-9a-f]{40}$"
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
