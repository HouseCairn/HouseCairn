#!/usr/bin/env bash
# Run a command again after a failure, for downloads the CI does itself
# (docs/adr/0014, "Rules every workflow follows"). Used for `docker pull`,
# which has no retry option of its own; curl and apt-get use theirs.
#
# Usage: .github/scripts/retry.sh <command> [<argument>...]
#
# At most RETRY_ATTEMPTS attempts (default 4), RETRY_DELAY seconds after the
# first failure (default 5), doubled after each one: 5, 10 and 20 s. The exit
# status is 0 as soon as one attempt succeeds, otherwise that of the last
# attempt: a download that never succeeds still fails the step. What the
# command fetched is verified by the caller as before (image digests, checksums).
set -euo pipefail

[ "$#" -gt 0 ] || { echo "usage: retry.sh <command> [<argument>...]" >&2; exit 2; }
attempts=${RETRY_ATTEMPTS:-4}
delay=${RETRY_DELAY:-5}

for ((attempt = 1; ; attempt++)); do
  status=0
  "$@" || status=$?
  [ "$status" -eq 0 ] && exit 0
  if [ "$attempt" -ge "$attempts" ]; then
    echo "retry.sh: $1 failed ${attempt} times, last exit status ${status}" >&2
    exit "$status"
  fi
  echo "retry.sh: $1 failed with exit status ${status} (attempt ${attempt} of ${attempts}), next attempt in ${delay} s" >&2
  sleep "$delay"
  delay=$((delay * 2))
done
