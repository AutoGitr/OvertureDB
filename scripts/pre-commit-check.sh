#!/usr/bin/env bash
set -euo pipefail
FIX=false
case "${1:-}" in
    "") ;;
    --fix) FIX=true ;;
    *) echo "Usage: $0 [--fix]" >&2; exit 2 ;;
esac
cd "$(dirname "$0")/.."
if [ "$FIX" = true ]; then
    uv lock
fi
if ! uv lock --check; then
    echo "uv.lock does not match pyproject.toml. Run 'uv lock' and commit uv.lock." >&2
    exit 1
fi
if [ "$FIX" = true ]; then
    uv run --locked ruff format scripts schema tests
    uv run --locked ruff check --fix scripts schema tests
else
    uv run --locked ruff format --check scripts schema tests
    uv run --locked ruff check scripts schema tests
fi
uv run --locked zizmor --offline --quiet .github/workflows
uv run --locked pyright
uv run --locked python -m pytest --cov
uv run --locked python -m scripts.catalog validate
if [ -d ../Overture/src/overture ]; then
    uv run --directory ../Overture --locked python -m scripts.preset_contract "$PWD" --check
    uv run --directory ../Overture --locked python -m scripts.catalog_contract "$PWD" --check
    uv run --directory ../Overture --locked python -m pytest tests/test_release/test_shared_files.py -p no:cacheprovider --no-cov
else
    echo "No Overture checkout at ../Overture; skipping the contract drift check."
fi
