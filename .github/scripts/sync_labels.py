"""Preview managed labels; --apply creates/updates them without deleting history."""

import argparse
import json
from pathlib import Path
from typing import Any

from automation import gh


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="AutoGitr/OvertureDB")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    labels: list[dict[str, Any]] = json.loads(
        (Path(__file__).resolve().parents[1] / "labels.json").read_text(
            encoding="utf-8"
        )
    )
    for label in labels:
        if args.apply:
            gh(
                "label",
                "create",
                label["name"],
                "--repo",
                args.repo,
                "--force",
                "--color",
                label["color"],
                "--description",
                label["description"],
            )
        print(f"{label['name']}: {label['description']}")  # noqa: T201


if __name__ == "__main__":
    main()
