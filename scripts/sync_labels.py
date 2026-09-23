"""Reconcile all repository labels with labels.json; preview unless --apply."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, NotRequired, TypedDict
from urllib.parse import quote, urlencode

from automation import gh


class Label(TypedDict):
    name: str
    color: str
    description: str
    aliases: NotRequired[list[str]]


def load_labels() -> list[Label]:
    labels: list[Label] = json.loads(
        (Path(__file__).resolve().parents[1] / ".github/labels.json").read_text(
            encoding="utf-8"
        )
    )
    names: set[str] = set()
    for label in labels:
        if not re.fullmatch(r"[0-9a-f]{6}", label["color"]):
            raise ValueError(f"Invalid color for {label['name']}")
        if not label["description"] or len(label["description"]) > 100:
            raise ValueError(f"Invalid description for {label['name']}")
        for name in [label["name"], *label.get("aliases", [])]:
            if not name or name != name.strip() or name.casefold() in names:
                raise ValueError(f"Empty, ambiguous or duplicate label: {name!r}")
            names.add(name.casefold())
    if not labels:
        raise ValueError("The label manifest must not be empty")
    return labels


def pages(path: str) -> list[dict[str, Any]]:
    result: list[list[dict[str, Any]]] = json.loads(
        gh("api", path, "--paginate", "--slurp")
    )
    return [item for page in result for item in page]


def sync(repo: str, labels: list[Label], *, apply: bool) -> bool:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("Repository must be OWNER/REPO")
    base = f"repos/{repo}"
    existing = {item["name"]: item for item in pages(f"{base}/labels?per_page=100")}
    managed = {
        name for label in labels for name in [label["name"], *label.get("aliases", [])]
    }
    unknown = existing.keys() - managed
    if unknown:
        raise ValueError(
            "Unmanaged labels: "
            + ", ".join(sorted(unknown))
            + ". Add definitions or merge aliases to labels.json before applying."
        )
    changed = False
    for label in labels:
        name = label["name"]
        fields = {
            "name": name,
            "color": label["color"],
            "description": label["description"],
        }
        current = existing.get(name)
        if current is None or any(
            current[key] != value for key, value in fields.items()
        ):
            changed = True
            print(f"{'Create' if current is None else 'Update'} {name}")
            if apply:
                if current is None:
                    gh("api", f"{base}/labels", "--method", "POST", payload=fields)
                else:
                    gh(
                        "api",
                        f"{base}/labels/{quote(name, safe='')}",
                        "--method",
                        "PATCH",
                        payload={
                            "new_name": name,
                            "color": label["color"],
                            "description": label["description"],
                        },
                    )
        for alias in label.get("aliases", []):
            if alias not in existing:
                continue
            changed = True
            query = urlencode({"state": "all", "labels": alias, "per_page": 100})
            # Includes closed issues and PRs, without the search API's result limit.
            items = pages(f"{base}/issues?{query}")
            print(f"Merge {alias} into {name} ({len(items)} issues/PRs)")
            if apply:
                for item in items:
                    gh(
                        "api",
                        f"{base}/issues/{item['number']}/labels",
                        "--method",
                        "POST",
                        payload={"labels": [name]},
                    )
                # Preserve every assignment before deleting. Failed runs are retryable.
                gh(
                    "api",
                    f"{base}/labels/{quote(alias, safe='')}",
                    "--method",
                    "DELETE",
                )
    if not changed:
        print("Labels match labels.json.")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="AutoGitr/OvertureDB")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true", help="Exit 1 if labels differ")
    args = parser.parse_args()
    try:
        changed = sync(args.repo, load_labels(), apply=args.apply)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Label synchronization failed: {exc}", file=sys.stderr)
        return 1
    return int(args.check and changed)


if __name__ == "__main__":
    raise SystemExit(main())
