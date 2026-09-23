#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv lock --check
uv run --locked ruff check .github/scripts schema
uv run --locked ruff format --check .github/scripts schema
uv run --locked pyright
uv run --locked python -m unittest discover -s .github/scripts -p 'test_*.py'
uv run --locked python .github/scripts/catalog.py validate
