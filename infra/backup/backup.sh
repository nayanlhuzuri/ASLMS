#!/bin/sh
# Nightly backup (plan §8.2): a compressed PostgreSQL dump and a copy of the document storage.
# Runs inside the `backup` service (docker-compose.prod.yml) once a day at BACKUP_HOUR (IST), and can be run by hand:
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm backup /backup.sh once
# Keeps BACKUP_KEEP_DAYS days. Copy /backups off the server (State Data Centre backup policy) — a backup on the
# same disk is not a backup.
set -eu

: "${PGHOST:=postgres}" "${PGUSER:=aslms}" "${PGDATABASE:=aslms}"
: "${BACKUP_DIR:=/backups}" "${BACKUP_KEEP_DAYS:=14}" "${BACKUP_HOUR:=1}" "${STORAGE_DIR:=/data/storage}"

run_backup() {
    stamp=$(date +%Y%m%d-%H%M%S)
    mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/storage"
    echo "[$stamp] dumping database $PGDATABASE"
    pg_dump -Fc -Z 6 -f "$BACKUP_DIR/db/aslms-$stamp.dump.part" "$PGDATABASE"
    mv "$BACKUP_DIR/db/aslms-$stamp.dump.part" "$BACKUP_DIR/db/aslms-$stamp.dump"
    # the database roles (aslms_owner, aslms_app, aslms_readonly) are cluster objects and are not in a
    # database dump; a restore on a fresh server replays this file first (DB_STANDARD §8)
    pg_dumpall --roles-only -f "$BACKUP_DIR/db/roles-$stamp.sql"
    echo "[$stamp] syncing document storage"
    # storage is content-addressed (sha256 names), so copying new files is enough
    cp -Rn "$STORAGE_DIR/." "$BACKUP_DIR/storage/" 2>/dev/null || true
    find "$BACKUP_DIR/db" \( -name 'aslms-*.dump' -o -name 'roles-*.sql' \) -mtime "+$BACKUP_KEEP_DAYS" -delete
    echo "[$stamp] done: $(ls -1 "$BACKUP_DIR/db" | wc -l) dump(s) kept"
}

if [ "${1:-loop}" = "once" ]; then
    run_backup
    exit 0
fi

while true; do
    now_h=$(TZ=Asia/Kolkata date +%H | sed 's/^0//')
    if [ "${now_h:-0}" -eq "$BACKUP_HOUR" ]; then
        run_backup || echo "backup FAILED" >&2
        sleep 3700   # past the hour, so it runs once
    fi
    sleep 300
done
