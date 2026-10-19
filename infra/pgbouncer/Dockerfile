# PgBouncer in front of the application's database connections (design deployment-checklist, Part C, decision 29).
# Built from pinned Alpine; PgBouncer 1.21 or later is required, because psycopg 3 prepares statements at the
# protocol level and only 1.21+ tracks them in transaction mode (max_prepared_statements).
FROM alpine:3.23.3

RUN apk add --no-cache 'pgbouncer>=1.21' \
    && pgbouncer --version \
    && addgroup -S -g 10001 pgbouncer \
    && adduser -S -D -H -u 10001 -G pgbouncer -s /sbin/nologin pgbouncer

COPY entrypoint.sh /usr/local/bin/pgbouncer-entrypoint.sh
RUN chmod 0755 /usr/local/bin/pgbouncer-entrypoint.sh

# an unprivileged user (uid 10001, as in the backend image); the configuration and the user list are written to
# /tmp at start (a tmpfs in Compose), never into the image
USER 10001
EXPOSE 6432
ENTRYPOINT ["/bin/sh", "/usr/local/bin/pgbouncer-entrypoint.sh"]
