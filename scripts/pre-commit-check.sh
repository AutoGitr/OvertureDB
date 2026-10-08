#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! uv lock --check; then
    echo "uv.lock does not match pyproject.toml. Run 'uv lock' and commit uv.lock." >&2
    exit 1
fi
uv run --locked ruff check scripts schema tests
uv run --locked ruff format --check scripts schema tests
uv run --locked pyright
uv run --locked python -m unittest discover -s tests -t . -p 'test_*.py'
uv run --locked python scripts/catalog.py validate
if [ -d ../Overture/backend ]; then
    uv run --locked python ../Overture/scripts/dataset_contract.py . --check
else
    echo "No Overture checkout at ../Overture; skipping the contract drift check."
fi
