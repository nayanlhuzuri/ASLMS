#!/bin/sh
# The PgBouncer healthcheck (design pre-pilot-hardening, decision 8): logs in through the pool as aslms_app and runs
# SELECT 1, so "healthy" means the application can log in (a wrong password or an unreachable Postgres fails it).
# The password reaches psql only as PGPASSWORD, taken from the container's ASLMS_APP_PASSWORD: never on a command
# line, never in compose.yml, never echoed, never written to disk. psql's error line carries no secret.
set -eu
: "${ASLMS_APP_PASSWORD:?}"
export PGPASSWORD="$ASLMS_APP_PASSWORD"
export PGCONNECT_TIMEOUT=3
out=$(psql -X -A -t -h 127.0.0.1 -p 6432 -U aslms_app -d "${POSTGRES_DB:-aslms}" -c 'SELECT 1')
[ "$out" = "1" ]
