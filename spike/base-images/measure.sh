#!/usr/bin/env bash
# Spike only (spike/base-images/README.md): build one candidate image and
# measure it. Run by .github/workflows/spike-base-images.yml, one job per
# candidate and architecture, on a fresh runner.
#
# Usage: spike/base-images/measure.sh <candidate> <output directory>
#   candidate: current | distroless | wolfi | chainguard
# Environment: GRYPE and SYFT (paths of the scanners), PG_URL (DATABASE_URL of
# the PostgreSQL service, reached through the host name pg.internal).
#
# Writes <output directory>/<candidate>-<arch>.json and the raw reports. Never
# runs a shell inside the candidate: every check inside the container is a
# Python one-liner, so images without a shell are tested the same way.
set -euo pipefail

CANDIDATE=${1:?usage: measure.sh <candidate> <output directory>}
OUT=${2:?usage: measure.sh <candidate> <output directory>}
: "${GRYPE:?}" "${SYFT:?}" "${PG_URL:?}"
HERE=$(cd "$(dirname "$0")" && pwd)
ARCH=$(docker version -f '{{.Server.Arch}}')
IMAGE="spike-$CANDIDATE:measure"
NAME="spike-$CANDIDATE"
NETWORK="spike-net"
PORT=18000
mkdir -p "$OUT"
RESULT="$OUT/$CANDIDATE-$ARCH.json"
PREFIX="$OUT/$CANDIDATE-$ARCH"

case "$CANDIDATE" in
  current)
    DOCKERFILE=Dockerfile
    BASE="python:3.13.18-slim-trixie@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc" ;;
  distroless)
    DOCKERFILE=spike/base-images/Dockerfile.distroless
    BASE="gcr.io/distroless/python3-debian13:nonroot@sha256:1c32c3720dc4c7f0c7dbe998737f32c200add6511eca7cec705008be488b87d6" ;;
  wolfi)
    DOCKERFILE=spike/base-images/Dockerfile.wolfi
    BASE="" ;;
  chainguard)
    DOCKERFILE=spike/base-images/Dockerfile.chainguard
    BASE="cgr.dev/chainguard/python:latest@sha256:1a00964779bf570a8cb2ea4fa086614af19c35069029785c08fcec0c50b66ac0" ;;
  *) echo "unknown candidate: $CANDIDATE" >&2; exit 2 ;;
esac

echo '{}' >"$RESULT"
# put <key path> <JSON value>: set one field of the result file.
put() { jq --argjson v "$2" "$1 = \$v" "$RESULT" >"$RESULT.tmp" && mv "$RESULT.tmp" "$RESULT"; }
str() { jq -Rn --arg s "$1" '$s'; }
# check <name> <pass|fail|absent|present> <detail>
check() {
  put ".checks[\"$1\"]" "$(jq -n --arg s "$2" --arg d "$3" '{status: $s, detail: $d}')"
  printf '%-22s %-8s %s\n' "$1" "$2" "$3"
}

put .candidate "$(str "$CANDIDATE")"
put .arch "$(str "$ARCH")"
put .dockerfile "$(str "$DOCKERFILE")"

# --- Build ---------------------------------------------------------------------
started=$(date +%s)
if docker build --progress=plain -f "$DOCKERFILE" --build-arg VERSION=spike \
    --build-arg REVISION="${GITHUB_SHA:-unknown}" -t "$IMAGE" . >"$PREFIX-build.log" 2>&1; then
  put .build "$(jq -n --argjson s $(($(date +%s) - started)) '{ok: true, seconds: $s}')"
  TARGET=$IMAGE
else
  reason=$(grep -m 3 -iE 'error|incompatible|requires' "$PREFIX-build.log" | cut -c1-300 | tr '\n' ' ')
  put .build "$(jq -n --argjson s $(($(date +%s) - started)) --arg r "$reason" \
    '{ok: false, seconds: $s, reason: $r}')"
  echo "build failed: $reason" >&2
  [ -n "$BASE" ] || exit 0
  # The application could not be built: measure the bare base image instead.
  docker pull -q "$BASE" >/dev/null
  TARGET=$BASE
fi
put .measured "$(str "$([ "$TARGET" = "$IMAGE" ] && echo application || echo "base only: $BASE")")"

# --- Image: sizes, layers, user, interpreter ------------------------------------------
measure_image() { # <image> <key>
  docker save "$1" -o "$PREFIX-image.tar"
  put ".$2.layers" "$(python3 "$HERE/layers.py" "$PREFIX-image.tar")"
  rm -f "$PREFIX-image.tar"
  put ".$2.user" "$(str "$(docker image inspect -f '{{.Config.User}}' "$1")")"
  put ".$2.python" "$(str "$(docker run --rm --network none --entrypoint python "$1" -c \
    'import platform; print(platform.python_version(), *platform.libc_ver())' 2>&1 | tail -n 1)")"
}
measure_image "$TARGET" image

# Files of the image, read without running it: shell, package managers, pip.
docker create --name "$NAME-files" "$TARGET" >/dev/null
docker export "$NAME-files" | tar -t >"$PREFIX-files.txt"
docker rm "$NAME-files" >/dev/null
find_files() { grep -E "$1" "$PREFIX-files.txt" | sort -u | tr '\n' ' ' || true; }
shells=$(find_files '^(usr/)?bin/(sh|bash|dash|ash|busybox)$')
managers=$(find_files '^(usr/)?s?bin/(apt|apt-get|dpkg|apk|rpm|microdnf|yum)$')
pips=$(find_files '(^|/)bin/pip[0-9.]*$')
put .files "$(jq -n --arg s "$shells" --arg m "$managers" --arg p "$pips" \
  --argjson n "$(wc -l <"$PREFIX-files.txt")" \
  '{entries: $n, shells: $s, package_managers: $m, pip: $p}')"

# --- Vulnerabilities (Grype, same version and gate as image.yml) ------------------------
scan() { # <image> <key>
  GRYPE_CHECK_FOR_APP_UPDATE=false "$GRYPE" "docker:$1" -q -o "json=$PREFIX-$2-grype.json"
  put ".$2.grype" "$(jq '
    [.matches[] | {s: .vulnerability.severity, f: (.vulnerability.fix.state == "fixed")}] as $m
    | {total: ($m | length), fixable: ($m | map(select(.f)) | length),
       by_severity: ($m | group_by(.s) | map({key: .[0].s,
         value: {total: length, fixable: (map(select(.f)) | length)}}) | from_entries),
       ci_gate_failures: ($m | map(select(.f and (.s == "High" or .s == "Critical"))) | length)}
  ' "$PREFIX-$2-grype.json")"
}
scan "$TARGET" image
if [ -n "$BASE" ] && [ "$TARGET" != "$BASE" ]; then
  docker pull -q "$BASE" >/dev/null
  measure_image "$BASE" base
  scan "$BASE" base
fi

# --- SBOM (Syft) -------------------------------------------------------------------------
SYFT_CHECK_FOR_APP_UPDATE=false "$SYFT" "docker:$TARGET" -q -o "syft-json=$PREFIX-sbom.json"
put .sbom "$(jq '{packages: (.artifacts | length),
  by_type: (.artifacts | group_by(.type) | map({key: .[0].type, value: length}) | from_entries)}' \
  "$PREFIX-sbom.json")"

[ "$TARGET" = "$IMAGE" ] || exit 0

# --- Run: SQLite, then PostgreSQL ---------------------------------------------------------
docker network create "$NETWORK" >/dev/null
GATEWAY=$(docker network inspect -f '{{(index .IPAM.Config 0).Gateway}}' "$NETWORK")
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm -f "$NAME-data" >/dev/null 2>&1 || true
}
trap 'cleanup; docker network rm "$NETWORK" >/dev/null 2>&1 || true' EXIT

start() { # <label> [extra docker run arguments]
  local label=$1 started status
  shift
  cleanup
  docker volume create "$NAME-data" >/dev/null
  docker run -d --name "$NAME" --network "$NETWORK" --add-host pg.internal:host-gateway \
    --read-only --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m -v "$NAME-data:/data" -p "127.0.0.1:$PORT:8000" \
    --env-file deploy/production.env.example -e ALLOWED_HOSTS=localhost \
    -e CSRF_TRUSTED_ORIGINS=https://localhost -e "HOUSECAIRN_FORWARDED_ALLOW_IPS=$GATEWAY" \
    "$@" "$IMAGE" >/dev/null
  started=$(date +%s)
  for _ in $(seq 1 120); do
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$NAME")
    if [ "$status" = healthy ]; then
      check "start_$label" pass "healthy after $(($(date +%s) - started)) s"
      return 0
    fi
    [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = true ] || break
    sleep 2
  done
  docker logs --tail 60 "$NAME" >"$PREFIX-$label-start.log" 2>&1 || true
  check "start_$label" fail "not healthy (status '${status:-none}'), see $label-start.log"
  return 1
}

http_get() { # <path> <body file>; prints the status code
  curl -4 -sS -o "$2" -w '%{http_code}' -H 'X-Forwarded-Proto: https' "http://localhost:$PORT$1" \
    || echo 000
}
py() { docker exec "$NAME" python -c "$@"; }

functional() { # <label>
  local label=$1 out
  docker logs "$NAME" >"$PREFIX-$label.log" 2>&1
  if grep -q 'applying database migrations' "$PREFIX-$label.log" \
      && docker exec "$NAME" python -m housecairn.entrypoint manage migrate --check \
        >>"$PREFIX-$label.log" 2>&1; then
    check "migrate_$label" pass "applied at start, migrate --check clean"
  else
    check "migrate_$label" fail "see $label.log"
  fi
  out=$(mktemp)
  code=$(http_get /healthz "$out")
  if [ "$code" = 200 ] && [ "$(jq -c . "$out" 2>/dev/null)" = '{"status":"ok"}' ]; then
    check "healthz_$label" pass "200 {\"status\":\"ok\"}"
  else
    check "healthz_$label" fail "$code $(head -c 200 "$out")"
  fi
  code=$(http_get /accounts/login/ "$out")
  if [ "$code" = 200 ] && grep -q 'type="password"' "$out"; then
    check "login_page_$label" pass "200 with the sign-in form"
  else
    check "login_page_$label" fail "$code"
  fi
  if docker exec "$NAME" python -m housecairn.entrypoint manage shell \
      -c "$(cat "$HERE/photo_check.py")" >"$out" 2>>"$PREFIX-$label.log" \
      && line=$(grep -m 1 '^SPIKE-PHOTO ' "$out") \
      && jq -e '.JPEG.stored == "JPEG" and .PNG.stored == "PNG" and .WEBP.stored == "WEBP"' \
        <<<"${line#SPIKE-PHOTO }" >/dev/null; then
    check "photo_$label" pass "${line#SPIKE-PHOTO }"
  else
    check "photo_$label" fail "$(tail -n 3 "$out" | tr '\n' ' ' | cut -c1-300)"
  fi
  rm -f "$out"
}

if start sqlite; then
  functional sqlite
  if backup=$(docker exec "$NAME" python -m housecairn.entrypoint backup 2>&1) \
      && [ "$(py 'import sqlite3, sys; print(sqlite3.connect(sys.argv[1]).execute("pragma integrity_check").fetchone()[0])' \
        "$backup" 2>&1)" = ok ]; then
    check backup pass "$backup, integrity_check ok"
  else
    check backup fail "$backup"
  fi
  uid=$(py 'import os; print(os.getuid(), os.getgid())' 2>&1)
  if [ "$uid" = "10001 10001" ]; then check non_root pass "uid gid $uid"; else check non_root fail "$uid"; fi
  if py 'open("/app/probe", "w")' >/dev/null 2>&1; then
    check read_only fail "writing /app succeeded"
  else
    check read_only pass "writing /app refused, root file system read-only"
  fi
  if docker exec "$NAME" sh -c 'exit 0' >/dev/null 2>&1; then
    check exec_shell present "docker exec sh works (debugging in place possible)"
  else
    check exec_shell absent "no shell to docker exec into"
  fi
fi

if start postgresql -e "DATABASE_URL=$PG_URL"; then
  functional postgresql
fi

# Every check of the run must pass; exec_shell is information, not a check.
jq -e '[.checks // {} | to_entries[] | select(.key != "exec_shell") | .value.status]
  | all(. == "pass")' "$RESULT" >/dev/null
