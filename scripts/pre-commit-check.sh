#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv lock --check
uv run --locked ruff check scripts schema
uv run --locked ruff format --check scripts schema
uv run --locked pyright
uv run --locked python -m unittest discover -s scripts -p 'test_*.py'
uv run --locked python scripts/catalog.py validate
