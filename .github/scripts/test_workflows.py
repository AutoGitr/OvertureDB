"""Keep workflow permissions, pins, checks and label references consistent."""

import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class WorkflowTests(unittest.TestCase):
    def test_workflows_pin_actions_bound_runtime_and_do_not_persist_credentials(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(path=path.name):
                self.assertIn("permissions", workflow)
                for job in workflow["jobs"].values():
                    self.assertEqual(job["runs-on"], "ubuntu-24.04")
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
                            self.assertEqual(
                                step["with"]["python-version-file"], ".python-version"
                            )
                        run = step.get("run", "")
                        self.assertNotIn(
                            "${{",
                            run,
                            "Pass expressions through env, not shell interpolation",
                        )
                        self.assertNotRegex(run, r"uv run (?!\-\-locked)")

    def test_form_and_renovate_labels_exist_in_manifest(self):
        labels = json.loads((ROOT / ".github/labels.json").read_text(encoding="utf-8"))
        names = {label["name"] for label in labels}
        self.assertEqual(len(names), len(labels))
        for label in labels:
            self.assertTrue(re.fullmatch(r"[0-9a-f]{6}", label["color"]))
            self.assertTrue(label["description"])
        for path in (ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"):
            form = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertTrue(set(form.get("labels", [])) <= names)
        renovate = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
        self.assertTrue(set(renovate["labels"]) <= names)
        self.assertTrue(set(renovate["vulnerabilityAlerts"]["labels"]) <= names)
        for rule in renovate["packageRules"]:
            self.assertTrue(set(rule.get("addLabels", [])) <= names)

    def test_all_validation_jobs_use_the_same_gate(self):
        for name in ("contribution-guard", "import-themerrdb", "publish-catalog"):
            content = (ROOT / f".github/workflows/{name}.yml").read_text(
                encoding="utf-8"
            )
            self.assertIn("bash scripts/pre-commit-check.sh", content)
