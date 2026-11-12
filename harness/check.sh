#!/bin/bash
# check.sh <work tree>: build + existing unit tests + existing integration tests.
# Uses EXP_PORT and EXP_DB so parallel runs do not collide. Exit 0 only if everything passes.
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../scripts/env.sh"
W="$1"; PORT="${EXP_PORT:-18100}"; DB="${EXP_DB:-miniflux_check}"
cd "$W" || exit 2
out=$(go build ./... 2>&1) || { echo "BUILD FAILED"; echo "$out" | head -80; exit 1; }
out=$(go vet ./... 2>&1) || { echo "GO VET FAILED"; echo "$out" | head -80; exit 1; }
unit=$(go test -count=1 ./... 2>&1); urc=$?
if [ $urc -ne 0 ]; then
  echo "UNIT TESTS FAILED"
  echo "$unit" | grep -v -E '^ok |no test files' | head -150
  exit 1
fi
echo "unit tests: $(echo "$unit" | grep -c '^ok ') packages ok"
psql -q -c "drop database if exists $DB;" -c "create database $DB;" >/dev/null 2>&1
BIN="/tmp/exp-miniflux-$PORT"
go build -o "$BIN" . || exit 1
DATABASE_URL="postgres://postgres@127.0.0.1:55432/$DB?sslmode=disable" LISTEN_ADDR=127.0.0.1:$PORT \
ADMIN_USERNAME=admin ADMIN_PASSWORD=test123 CREATE_ADMIN=1 RUN_MIGRATIONS=1 LOG_LEVEL=debug \
FETCHER_ALLOW_PRIVATE_NETWORKS=1 INTEGRATION_ALLOW_PRIVATE_NETWORKS=1 \
"$BIN" >"/tmp/exp-miniflux-$PORT.log" 2>&1 &
PID=$!
up=0
for i in $(seq 40); do nc -z 127.0.0.1 $PORT 2>/dev/null && { up=1; break; }; kill -0 $PID 2>/dev/null || break; sleep 0.5; done
if [ $up -ne 1 ]; then
  echo "SERVER FAILED TO START"; tail -30 "/tmp/exp-miniflux-$PORT.log"; kill $PID 2>/dev/null
  psql -q -c "drop database if exists $DB;" >/dev/null 2>&1; exit 1
fi
integ=$(TEST_MINIFLUX_BASE_URL=http://127.0.0.1:$PORT TEST_MINIFLUX_ADMIN_USERNAME=admin TEST_MINIFLUX_ADMIN_PASSWORD=test123 \
  go test -v -count=1 ./internal/api 2>&1); irc=$?
kill $PID 2>/dev/null; wait $PID 2>/dev/null
psql -q -c "drop database if exists $DB;" >/dev/null 2>&1
if [ $irc -ne 0 ]; then
  echo "INTEGRATION TESTS FAILED"
  echo "$integ" | grep -E -B2 -A12 '^--- FAIL|^panic|^FAIL' | head -150
  exit 1
fi
echo "integration tests: $(echo "$integ" | grep -c '^--- PASS') passed"
