#!/usr/bin/env bash
# Download one asset of a GitHub release through the REST API, for the tools
# the CI installs itself (docs/adr/0014, "Rules every workflow follows").
#
# Usage: GITHUB_TOKEN=<token> .github/scripts/release-asset.sh \
#          <owner>/<repository> <tag> <asset file name> <output file>
#
# Why the API and not https://github.com/<owner>/<repository>/releases/download/:
# on 2026-11-08 that address answered 504 for minutes on end, from GitHub
# Actions and from outside, while the API kept answering and served the same
# file. The API is the only path, not a fallback: a single code path, and no
# attempt spent on an address known to fail.
#
# 1. GET /repos/<owner>/<repository>/releases/tags/<tag> gives the id of the
#    asset with exactly that name, read at run time (no id in the workflows).
# 2. GET /repos/<owner>/<repository>/releases/assets/<id> with
#    `Accept: application/octet-stream` redirects to the file; curl follows it
#    (-L) and does not send the Authorization header to the other host.
#
# Both requests use the retry options of every curl of the CI, and --fail: an
# HTTP error on the last attempt exits non-zero, and so does a missing asset.
# GITHUB_TOKEN (the job's read-only token) is only there for the API rate
# limit; it is sent as a header and never printed. The caller verifies the
# file against its pinned SHA-256 afterwards, as before.
set -euo pipefail

[ "$#" -eq 4 ] || {
  echo "usage: release-asset.sh <owner>/<repository> <tag> <asset file name> <output file>" >&2
  exit 2
}
repo=$1
tag=$2
name=$3
output=$4
: "${GITHUB_TOKEN:?release-asset.sh: GITHUB_TOKEN must be set (read-only token, for the API rate limit)}"
api=${GITHUB_API_URL:-https://api.github.com}

curl_options=(
  -sSfL --retry 4 --retry-delay "${RELEASE_ASSET_RETRY_DELAY:-5}" --retry-all-errors --retry-max-time 120
  -H "Authorization: Bearer ${GITHUB_TOKEN}"
  -H "X-GitHub-Api-Version: 2022-11-28"
)

release=$(curl "${curl_options[@]}" -H "Accept: application/vnd.github+json" \
  "${api}/repos/${repo}/releases/tags/${tag}")
id=$(jq -er --arg name "$name" \
  '[.assets[] | select(.name == $name) | .id] | if length == 1 then .[0] else empty end' \
  <<<"$release") || {
  echo "release-asset.sh: no single asset named ${name} in release ${tag} of ${repo}" >&2
  exit 1
}
[[ "$id" =~ ^[0-9]+$ ]] || { echo "release-asset.sh: unexpected asset id: ${id}" >&2; exit 1; }

echo "release-asset.sh: downloading ${name} (${repo} ${tag}) from ${api}/repos/${repo}/releases/assets/${id}"
curl "${curl_options[@]}" -H "Accept: application/octet-stream" -o "$output" \
  "${api}/repos/${repo}/releases/assets/${id}"
