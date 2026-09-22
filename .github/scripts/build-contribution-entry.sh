#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: build-contribution-entry.sh <issue-body-file> <issue-title> <labels-file> <output-root>" >&2
}

[ "$#" -eq 4 ] || {
  usage
  exit 2
}

body_file="$1"
issue_title="$2"
labels_file="$3"
output_root="$4"

uv run python .github/scripts/contribution.py \
  --issue-body-file "$body_file" \
  --issue-title "$issue_title" \
  --labels-file "$labels_file" \
  --repo-root "$output_root"
