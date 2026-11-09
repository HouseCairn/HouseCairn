#!/usr/bin/env bash
# Downloads the Grype vulnerability database while the image builds and is
# tested, so that the scan does not wait for it (docs/adr/0015, amendment of
# 2026-11-09). Run by image.yml.
#
# Usage: .github/scripts/grype-db.sh start <grype binary> <state directory>
#        .github/scripts/grype-db.sh wait <state directory>
#
# `start` returns at once; the download goes on in the background and its exit
# status is written to <state directory>/status. `wait` blocks until it is
# there and fails, with the log, if the download failed or took too long: the
# scan never runs on a missing database.
set -euo pipefail

mode=${1:?usage: grype-db.sh start <grype binary> <state directory> | wait <state directory>}

case "$mode" in
  start)
    grype=${2:?grype binary}
    state=${3:?state directory}
    mkdir -p "$state"
    rm -f "$state/status"
    (
      status=0
      GRYPE_CHECK_FOR_APP_UPDATE=false "$grype" db update >"$state/log" 2>&1 || status=$?
      echo "$status" >"$state/status"
    ) >/dev/null 2>&1 &
    echo "Grype database download started in the background"
    ;;
  wait)
    state=${2:?state directory}
    deadline=$((SECONDS + 300))
    while [ ! -f "$state/status" ]; do
      if [ "$SECONDS" -ge "$deadline" ]; then
        echo "The Grype database download did not finish in 300 s" >&2
        cat "$state/log" >&2 || true
        exit 1
      fi
      sleep 1
    done
    status=$(cat "$state/status")
    cat "$state/log"
    if [ "$status" != 0 ]; then
      echo "The Grype database download failed (exit status $status)" >&2
      exit 1
    fi
    ;;
  *)
    echo "usage: grype-db.sh start <grype binary> <state directory> | wait <state directory>" >&2
    exit 2
    ;;
esac
