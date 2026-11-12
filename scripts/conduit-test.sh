#!/bin/bash
# usage: conduit-test.sh <conduit checkout> <port> <outprefix>
# Runs go unit tests + RealWorld Hurl suite (spec pinned at repos/realworld-spec). rc=0 iff both pass.
source "$(dirname "$0")/env.sh"
SRC="$1"; PORT="${2:-18081}"; OUT="$3"
SPEC="$EXP/repos/realworld-spec/specs/api"
cd "$SRC" || exit 2
go test -count=1 ./... > "$OUT-unit.txt" 2>&1; URC=$?
go build -o /tmp/conduit-$PORT . || exit 3
DBF=$(mktemp -u /tmp/conduit-$PORT-XXXX.db)
DB_PATH=$DBF PORT=$PORT GIN_MODE=release /tmp/conduit-$PORT >/tmp/conduit-$PORT.log 2>&1 &
PID=$!
for i in $(seq 30); do nc -z 127.0.0.1 $PORT 2>/dev/null && break; sleep 1; done
HOST=http://127.0.0.1:$PORT bash "$SPEC/run-api-tests-hurl.sh" > "$OUT-hurl.txt" 2>&1; HRC=$?
kill $PID; rm -f $DBF
echo "unit rc=$URC hurl rc=$HRC"
[ $URC -eq 0 ] && [ $HRC -eq 0 ]
