#!/usr/bin/env bash
# Decides whether the image build must include linux/arm64 (docs/adr/0015,
# amendment of 2026-11-09), for the `changes` job of image.yml.
#
# Usage: .github/scripts/arm64-needed.sh <event name> <base sha> <head sha>
#
# arm64 is built under QEMU and is the slowest part of the workflow. It is
# built when the event publishes (`push`), or when the change touches what
# decides how the image is built: the Dockerfile, the build context filter, the
# locked dependencies, the project metadata, or this workflow and its scripts.
# Anything unknown (no base, a failing diff, an unexpected event) builds arm64:
# the check can only be skipped on evidence.
#
# Prints the reason, and writes `arm64=true|false` to $GITHUB_OUTPUT when set.
set -euo pipefail

event=${1:?usage: arm64-needed.sh <event name> <base sha> <head sha>}
base=${2:-}
head=${3:-}

# Paths whose change can alter the arm64 build (extended regular expression,
# whole path).
WATCHED='Dockerfile|\.dockerignore|uv\.lock|pyproject\.toml|\.github/workflows/image\.yml|\.github/scripts/(arm64-needed|retry)\.sh'

decide() {
  printf '%s\n' "arm64=$1 ($2)"
  printf 'arm64=%s\n' "$1" >>"${GITHUB_OUTPUT:-/dev/null}"
  exit 0
}

case "$event" in
  pull_request | merge_group) ;;
  push) decide true "the event publishes both platforms" ;;
  *) decide true "unexpected event $event" ;;
esac

[ -n "$base" ] && [ -n "$head" ] || decide true "no base or head commit"
files=$(git diff --name-only "$base...$head") || decide true "the diff could not be read"
[ -n "$files" ] || decide true "the diff is empty"

if hits=$(printf '%s\n' "$files" | grep -xE "$WATCHED"); then
  decide true "changed: $(printf '%s' "$hits" | tr '\n' ' ')"
fi
decide false "no change to the Dockerfile, the dependencies or this workflow"
