#!/usr/bin/env bash
# Smoke test of the container image (docs/adr/0015), run by image.yml.
#
# Usage: .github/scripts/image-smoke.sh <image> sqlite|postgresql
#
# Starts the image the way docs/install.md recommends (read-only root file
# system, no capability, no privilege escalation, /tmp in memory, an empty
# volume on /data), then checks that it becomes healthy, serves its pages and
# static files as an unprivileged user, cannot write outside /data and /tmp,
# keeps its database and secret key across a restart without migrating twice,
# stops cleanly on SIGTERM, and stops when one of its processes dies.
# Every check prints PASS or FAIL and is added to the job summary.
set -euo pipefail

IMAGE=${1:?usage: image-smoke.sh <image> sqlite|postgresql}
DB=${2:?usage: image-smoke.sh <image> sqlite|postgresql}
case "$DB" in
  sqlite) PORT=18000 ;;
  postgresql) PORT=18001 ;;
  *) echo "unknown database: $DB" >&2; exit 2 ;;
esac

NAME="hc-smoke-$DB"
VOLUME="hc-smoke-$DB-data"
NETWORK="hc-smoke-$DB-net"
PG_NAME="hc-smoke-postgres"
# Same image and digest as the PostgreSQL tests of ci.yml.
PG_IMAGE="postgres:18.6-alpine3.24@sha256:123b17998ccaf47e53b502e8c6a1e79afd8f579c6f3eec83c563da026f957395"
SUMMARY=${GITHUB_STEP_SUMMARY:-/dev/null}

summary() { printf '%s\n' "$*" >>"$SUMMARY"; }
pass() { printf 'PASS: %s\n' "$*"; summary "- PASS: $*"; }
fail() {
  printf 'FAIL: %s\n' "$*" >&2
  summary "- **FAIL: ${*}**"
  echo "--- last container logs ---" >&2
  docker logs --tail 80 "$NAME" >&2 2>&1 || true
  exit 1
}

cleanup() {
  docker rm -f "$NAME" "$PG_NAME" >/dev/null 2>&1 || true
  docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

summary "### Smoke test ($DB)"
docker network create "$NETWORK" >/dev/null
docker volume create "$VOLUME" >/dev/null

# The example production environment, for a local host name.
ENV_ARGS=(
  --env-file deploy/production.env.example
  -e ALLOWED_HOSTS=localhost
  -e CSRF_TRUSTED_ORIGINS=https://localhost
)

if [ "$DB" = postgresql ]; then
  PG_PASSWORD=$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')
  docker run -d --name "$PG_NAME" --network "$NETWORK" \
    -e POSTGRES_USER=housecairn -e POSTGRES_DB=housecairn \
    -e POSTGRES_PASSWORD="$PG_PASSWORD" "$PG_IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    if docker exec "$PG_NAME" pg_isready -q -h 127.0.0.1 -U housecairn -d housecairn; then break; fi
    sleep 1
  done
  docker exec "$PG_NAME" pg_isready -q -h 127.0.0.1 -U housecairn -d housecairn || fail "PostgreSQL did not start"
  ENV_ARGS+=(-e "DATABASE_URL=postgres://housecairn:${PG_PASSWORD}@${PG_NAME}:5432/housecairn")
  pass "PostgreSQL server started ($PG_IMAGE)"
fi

start_container() {
  docker run -d --name "$NAME" --network "$NETWORK" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    -v "$VOLUME:/data" \
    -p "127.0.0.1:$PORT:8000" \
    "${ENV_ARGS[@]}" \
    "$IMAGE" >/dev/null
}

wait_healthy() {
  local started status
  started=$(date +%s)
  for _ in $(seq 1 120); do
    status=$(docker inspect -f '{{.State.Health.Status}}' "$NAME")
    if [ "$status" = healthy ]; then
      pass "healthcheck is healthy after $(($(date +%s) - started)) s ($1)"
      return 0
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" != true ]; then
      fail "container stopped before becoming healthy ($1)"
    fi
    sleep 2
  done
  fail "container not healthy after 240 s ($1)"
}

# GET a path as a browser behind the TLS proxy would; prints the status code.
http_get() {
  curl -4 -sS -o "${2:-/dev/null}" -D "${3:-/dev/null}" -w '%{http_code}' \
    -H 'X-Forwarded-Proto: https' "http://localhost:$PORT$1"
}

in_container() { docker exec "$NAME" "$@"; }
manage() { docker exec "$NAME" python -m housecairn.entrypoint manage "$@"; }

# --- First start, on an empty volume --------------------------------------
start_container
wait_healthy "first start, empty volume"

[ "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$NAME")" = true ] \
  || fail "root file system is not read-only"
pass "started with --read-only --cap-drop ALL --security-opt no-new-privileges"

body=$(mktemp)
code=$(http_get / "$body")
[ "$code" = 200 ] || fail "GET / answered $code"
pass "GET / answers 200"

code=$(http_get /accounts/login/ "$body")
[ "$code" = 200 ] || fail "GET /accounts/login/ answered $code"
grep -q 'type="password"' "$body" || fail "the sign-in page has no password field"
pass "GET /accounts/login/ answers 200 with the sign-in form"

css=$(grep -o '/static/css/app\.[0-9a-f]*\.css' "$body" | head -n 1)
[ -n "$css" ] || fail "no hashed stylesheet in the sign-in page"
headers=$(mktemp)
code=$(http_get "$css" /dev/null "$headers")
[ "$code" = 200 ] || fail "GET $css answered $code"
grep -qi '^cache-control:.*immutable' "$headers" || fail "$css is not served as immutable"
pass "static file $css served by the application, immutable"

uid=$(in_container id -u)
[ "$uid" != 0 ] || fail "the application runs as root"
[ "$uid" = 10001 ] || fail "unexpected user id $uid"
pass "id -u is $uid (not root)"

for path in /app/probe /etc/probe /probe; do
  if in_container sh -c "touch $path" 2>/dev/null; then
    fail "writing $path succeeded outside /data and /tmp"
  fi
done
pass "writing to /app, /etc and / is refused"
in_container sh -c 'touch /data/probe && rm /data/probe' || fail "/data is not writable"
in_container sh -c 'touch /tmp/probe && rm /tmp/probe' || fail "/tmp is not writable"
pass "/data and /tmp are writable"

key_mode=$(in_container stat -c '%a %u:%g' /data/secret_key)
[ "$key_mode" = "600 10001:10001" ] || fail "secret key file is $key_mode, expected 600 10001:10001"
key_hash=$(in_container sha256sum /data/secret_key | cut -d' ' -f1)
pass "secret key generated in /data/secret_key, mode 600, owned by 10001"

if [ "$DB" = sqlite ]; then
  in_container test -f /data/db.sqlite3 || fail "no SQLite database in /data"
  pass "SQLite database created in /data/db.sqlite3"
else
  if in_container test -e /data/db.sqlite3; then fail "a SQLite file exists although DATABASE_URL is PostgreSQL"; fi
  pass "no SQLite file: the database is PostgreSQL"
fi

# A record that must survive the restart. No account is created by the image
# itself; this one exists for the test only.
docker exec -e DJANGO_SUPERUSER_PASSWORD="smoke-$(od -An -tx1 -N8 /dev/urandom | tr -d ' \n')" \
  "$NAME" python -m housecairn.entrypoint manage createsuperuser --noinput \
  --email smoke@example.com >/dev/null || fail "createsuperuser failed"

# --- Clean stop on SIGTERM -------------------------------------------------
stop_started=$(date +%s)
docker stop -t 30 "$NAME" >/dev/null
stop_seconds=$(($(date +%s) - stop_started))
exit_code=$(docker inspect -f '{{.State.ExitCode}}' "$NAME")
[ "$exit_code" = 0 ] || fail "exit code $exit_code after docker stop"
docker logs "$NAME" 2>&1 | grep -q 'received SIGTERM, stopping' || fail "SIGTERM was not handled"
[ "$stop_seconds" -lt 25 ] || fail "docker stop took $stop_seconds s"
pass "docker stop: SIGTERM handled, exit code 0 in ${stop_seconds} s"

# --- Restart on the same volume ---------------------------------------------
logs_before=$(docker logs "$NAME" 2>&1 | wc -l)
docker start "$NAME" >/dev/null
wait_healthy "restart, same volume"
docker logs "$NAME" 2>&1 | tail -n +"$((logs_before + 1))" | grep -q 'No migrations to apply' \
  || fail "migrations were not idempotent on restart"
pass "migrations on restart: No migrations to apply"
[ "$(in_container sha256sum /data/secret_key | cut -d' ' -f1)" = "$key_hash" ] \
  || fail "the secret key changed on restart"
pass "secret key kept across the restart"
users=$(manage shell -c \
  'from housecairn.accounts.models import User; print(User.objects.filter(email="smoke@example.com").count())' \
  | tail -n 1)
[ "$users" = 1 ] || fail "the account created before the restart is missing ($users)"
pass "database kept across the restart"

# --- A process that dies stops the container -------------------------------
in_container python -c '
import os, signal
for pid in filter(str.isdigit, os.listdir("/proc")):
    try:
        ppid = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1]
        cmdline = open(f"/proc/{pid}/cmdline", "rb").read()
    except OSError:
        continue
    if ppid == "1" and b"qcluster" in cmdline:
        os.kill(int(pid), signal.SIGKILL)
        print("killed task worker", pid)
'
for _ in $(seq 1 30); do
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = true ] || break
  sleep 1
done
[ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = false ] \
  || fail "the container kept running after its task worker died"
exit_code=$(docker inspect -f '{{.State.ExitCode}}' "$NAME")
[ "$exit_code" != 0 ] || fail "the container exited with 0 after its task worker died"
pass "task worker killed: the container stopped with exit code $exit_code"

echo "All smoke checks passed ($DB)."
