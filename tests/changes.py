"""Applying planned file changes to a test checkout, as publication commits them."""

lazy from pathlib import Path
lazy from typing import Any


def apply_changes(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Write *plan*'s ``additions`` and remove its ``deletions`` under *root*.

    Returns:
        *plan*, so a test can apply a result where it reads it.
    """
    for name, content in plan["additions"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, newline="\n")
    for name in plan["deletions"]:
        (root / name).unlink()
    return plan
