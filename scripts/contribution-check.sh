#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash scripts/pre-commit-check.sh
uv audit --locked --preview-features audit-command
trivy fs --scanners secret --exit-code 1 .
