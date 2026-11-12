#!/bin/bash
# usage: miniflux-integration.sh <miniflux checkout> <port> <dbname> <outfile>
source "$(dirname "$0")/env.sh"
SRC="$1"; PORT="${2:-18080}"; DB="${3:-miniflux_test}"; OUT="$4"
psql -q -c "drop database if exists $DB;" -c "create database $DB;" || exit 2
cd "$SRC" && go build -o /tmp/miniflux-$PORT . || exit 3
DATABASE_URL="postgres://postgres@127.0.0.1:55432/$DB?sslmode=disable" LISTEN_ADDR=127.0.0.1:$PORT \
ADMIN_USERNAME=admin ADMIN_PASSWORD=test123 CREATE_ADMIN=1 RUN_MIGRATIONS=1 LOG_LEVEL=debug \
FETCHER_ALLOW_PRIVATE_NETWORKS=1 INTEGRATION_ALLOW_PRIVATE_NETWORKS=1 \
/tmp/miniflux-$PORT >/tmp/miniflux-$PORT.log 2>&1 &
PID=$!
for i in $(seq 60); do nc -z 127.0.0.1 $PORT && break; sleep 1; done
TEST_MINIFLUX_BASE_URL=http://127.0.0.1:$PORT TEST_MINIFLUX_ADMIN_USERNAME=admin TEST_MINIFLUX_ADMIN_PASSWORD=test123 \
go test -v -count=1 ./internal/api > "$OUT" 2>&1; RC=$?
kill $PID; psql -q -c "drop database if exists $DB;"
exit $RC
