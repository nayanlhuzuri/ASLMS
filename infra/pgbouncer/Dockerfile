# PgBouncer in front of the application's database connections (design deployment-checklist, Part C, decision 29).
# Built from pinned Alpine with PgBouncer pinned exactly (design pre-pilot-hardening, decision 7): 1.22 or later is
# required, psycopg's documented minimum for protocol-level prepared statements in transaction mode
# (max_prepared_statements). When Alpine republishes the package the build fails: change the pin on purpose.
# postgresql16-client brings psql for the login healthcheck (decision 8); its major version matches the server.
FROM alpine:3.23.3

RUN apk add --no-cache 'pgbouncer=1.25.1-r0' 'postgresql16-client=16.15-r0' \
    && pgbouncer --version \
    && addgroup -S -g 10001 pgbouncer \
    && adduser -S -D -H -u 10001 -G pgbouncer -s /sbin/nologin pgbouncer

COPY entrypoint.sh /usr/local/bin/pgbouncer-entrypoint.sh
COPY healthcheck.sh /usr/local/bin/pgbouncer-healthcheck.sh
RUN chmod 0755 /usr/local/bin/pgbouncer-entrypoint.sh /usr/local/bin/pgbouncer-healthcheck.sh

# an unprivileged user (uid 10001, as in the backend image); the configuration and the user list are written to
# /tmp at start (a tmpfs in Compose), never into the image
USER 10001
EXPOSE 6432
ENTRYPOINT ["/bin/sh", "/usr/local/bin/pgbouncer-entrypoint.sh"]
