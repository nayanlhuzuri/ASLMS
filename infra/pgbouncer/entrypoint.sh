#!/bin/sh
# Writes pgbouncer.ini, the HBA file and a mode-600 userlist.txt from the environment, then starts PgBouncer (design
# deployment-checklist, Part C, decision 29). Compose passes POSTGRES_DB, ASLMS_APP_PASSWORD and
# ASLMS_READONLY_PASSWORD from .env. The passwords go into the user list only; they are never printed and never
# appear on a command line (printf is a shell builtin; tr and sed read them from a pipe).
#
# Who may connect, all with SCRAM-SHA-256:
# - aslms_app to the application database (api, worker, scheduler), pooled in transaction mode;
# - aslms_readonly to the `pgbouncer` admin console only, as a stats user (SHOW commands), for the pgbouncer exporter.
# Nobody is an admin user, so PAUSE, KILL, RELOAD and SHUTDOWN are refused.
set -eu

: "${ASLMS_APP_PASSWORD:?set ASLMS_APP_PASSWORD in .env}"
: "${ASLMS_READONLY_PASSWORD:?set ASLMS_READONLY_PASSWORD in .env}"
DB="${POSTGRES_DB:-aslms}"
PG_HOST="${PGBOUNCER_SERVER_HOST:-postgres}"
PG_PORT="${PGBOUNCER_SERVER_PORT:-5432}"
MAX_CLIENT_CONN="${PGBOUNCER_MAX_CLIENT_CONN:-200}"
DEFAULT_POOL_SIZE="${PGBOUNCER_DEFAULT_POOL_SIZE:-20}"
MAX_PREPARED_STATEMENTS="${PGBOUNCER_MAX_PREPARED_STATEMENTS:-200}"
DIR=/tmp/pgbouncer

fail() {
  echo "pgbouncer: $1" >&2
  exit 1
}

case "$DB" in
  '' | *[!A-Za-z0-9_]*) fail "POSTGRES_DB must be letters, digits and _ only" ;;
esac
case "$PG_HOST" in
  '' | *[!A-Za-z0-9_.-]*) fail "PGBOUNCER_SERVER_HOST must be a host name" ;;
esac
for pair in "PGBOUNCER_SERVER_PORT=$PG_PORT" "PGBOUNCER_MAX_CLIENT_CONN=$MAX_CLIENT_CONN" \
  "PGBOUNCER_DEFAULT_POOL_SIZE=$DEFAULT_POOL_SIZE" "PGBOUNCER_MAX_PREPARED_STATEMENTS=$MAX_PREPARED_STATEMENTS"; do
  case "${pair#*=}" in
    '' | *[!0-9]*) fail "${pair%%=*} must be a whole number" ;;
  esac
done

# a value for a double-quoted userlist.txt field: one line, " doubled
uq() {
  printf '%s' "$1" | tr -d '\r\n' | sed 's/"/""/g'
}

umask 077
mkdir -p "$DIR"

{
  printf '"aslms_app" "%s"\n' "$(uq "$ASLMS_APP_PASSWORD")"
  printf '"aslms_readonly" "%s"\n' "$(uq "$ASLMS_READONLY_PASSWORD")"
} > "$DIR/userlist.txt"
chmod 600 "$DIR/userlist.txt"

cat > "$DIR/pgbouncer_hba.conf" <<EOF
# TYPE  DATABASE   USER            ADDRESS     METHOD
host    $DB        aslms_app       0.0.0.0/0   scram-sha-256
host    pgbouncer  aslms_readonly  0.0.0.0/0   scram-sha-256
EOF

cat > "$DIR/pgbouncer.ini" <<EOF
[databases]
; no user= here: each client logs in to Postgres as itself, with its password from the user list
$DB = host=$PG_HOST port=$PG_PORT dbname=$DB

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
unix_socket_dir =

auth_type = hba
auth_hba_file = $DIR/pgbouncer_hba.conf
auth_file = $DIR/userlist.txt
admin_users =
stats_users = aslms_readonly

; transaction pooling: the application uses only transaction-scoped features (SET LOCAL, pg_advisory_xact_lock);
; backend/tests/unit/test_pgbouncer.py refuses session-level ones
pool_mode = transaction
max_client_conn = $MAX_CLIENT_CONN
default_pool_size = $DEFAULT_POOL_SIZE
; psycopg 3 prepares statements at the protocol level; PgBouncer 1.21+ tracks them per server connection
max_prepared_statements = $MAX_PREPARED_STATEMENTS
server_reset_query =

; the exporter's driver (lib/pq) sends extra_float_digits at start-up
ignore_startup_parameters = extra_float_digits

log_connections = 0
log_disconnections = 0
EOF

echo "pgbouncer: transaction pooling for $DB on :6432 (max_client_conn $MAX_CLIENT_CONN, pool $DEFAULT_POOL_SIZE)"
exec pgbouncer "$DIR/pgbouncer.ini"
