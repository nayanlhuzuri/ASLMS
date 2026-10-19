# ASLMS backend image: the CLI, migrations, the API, the workers and the backup service.
# Design deployment-checklist: pinned base image (decision 21); postgresql-client-16 from the PostgreSQL apt repository
# so pg_dump / pg_restore match the server's major version (decision 13); runs as the unprivileged uid 10001
# (decision 16).
FROM python:3.12.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && . /etc/os-release \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY aslms ./aslms
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir ".[redis]" \
 && groupadd --system --gid 10001 aslms \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home aslms \
 && mkdir -p /data /backups && chown 10001:10001 /data /backups

USER 10001:10001
CMD ["aslms", "--help"]
