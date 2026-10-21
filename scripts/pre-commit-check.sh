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
uv run --locked python -m pytest --cov
uv run --locked python -m scripts.catalog validate
if [ -d ../Overture/src/overture ]; then
    uv run --directory ../Overture --locked python -m scripts.dataset_contract "$PWD" --check
else
    echo "No Overture checkout at ../Overture; skipping the contract drift check."
fi
