"""Reconcile all repository labels with labels.json; preview unless --apply."""

lazy import argparse
lazy import json
lazy import re
lazy import sys
lazy from pathlib import Path
lazy from typing import TypedDict
lazy from urllib.parse import quote

lazy from .github import api, pages


class Label(TypedDict, closed=True):
    name: str
    color: str
    description: str


def load_labels() -> list[Label]:
    labels: list[Label] = json.loads(
        (Path(__file__).resolve().parents[1] / ".github/labels.json").read_text()
    )
    names: set[str] = set()
    for label in labels:
        if not re.fullmatch(r"[0-9a-f]{6}", label["color"]):
            raise ValueError(f"Invalid color for {label['name']}")
        if not label["description"] or len(label["description"]) > 100:
            raise ValueError(f"Invalid description for {label['name']}")
        name = label["name"]
        if not name or name != name.strip() or name.casefold() in names:
            raise ValueError(f"Empty, ambiguous or duplicate label: {name!r}")
        names.add(name.casefold())
    if not labels:
        raise ValueError("The label manifest must not be empty")
    return labels


def sync(repo: str, labels: list[Label], *, apply: bool) -> bool:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ValueError("Repository must be OWNER/REPO")
    base = f"repos/{repo}"
    existing = {item["name"]: item for item in pages(f"{base}/labels?per_page=100")}
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
                    api(f"{base}/labels", fields, method="POST")
                else:
                    api(
                        f"{base}/labels/{quote(name, safe='')}",
                        {
                            "new_name": name,
                            "color": label["color"],
                            "description": label["description"],
                        },
                        method="PATCH",
                    )
    for name in sorted(existing.keys() - {label["name"] for label in labels}):
        changed = True
        print(f"Delete {name}")
        if apply:
            api(f"{base}/labels/{quote(name, safe='')}", method="DELETE")
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
