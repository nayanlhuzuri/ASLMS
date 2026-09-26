#!/bin/sh
# Restore a dump made by backup.sh into an EMPTY database (stop api, workers and beat first):
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backup /restore.sh /backups/db/aslms-YYYYMMDD-HHMMSS.dump
# Document files: copy /backups/storage back into the storage volume.
set -eu
dump="${1:?usage: restore.sh <dump file>}"
: "${PGHOST:=postgres}" "${PGUSER:=aslms}" "${PGDATABASE:=aslms}"
echo "restoring $dump into $PGDATABASE on $PGHOST"
pg_restore --clean --if-exists --no-owner -d "$PGDATABASE" "$dump"
echo "restore finished; run 'alembic upgrade head' if the dump predates the latest migration"
