# ASLMS backend image: the CLI, migrations, the API, the workers and the backup service.
# Design deployment-checklist: pinned base image (decision 21); postgresql-client-16 from the PostgreSQL apt repository
# so pg_dump / pg_restore match the server's major version (decision 13); runs as the unprivileged uid 10001
# (decision 16).
# Design dependency-locks (decisions 5, 6 and 12): the libraries come only from requirements/image.txt, the hashed
# export of backend/uv.lock whose versions CI's requirements/dev.txt holds too; wheels only and nothing outside the
# lock (the build backend is the lock's `build` group, hence --no-build-isolation). The export is installed before the
# code is copied, so that layer is rebuilt only when the lock changes, and it stays at /app/requirements/image.txt for
# the `migrate` source check. `pip check` and an import of what each service starts from stop the build on a broken or
# undeclared dependency (the kombu 5.7.0 outage of 3 Nov 2026), so a deploy keeps its old images.
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

COPY requirements/image.txt ./requirements/image.txt
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r requirements/image.txt

COPY pyproject.toml alembic.ini ./
COPY aslms ./aslms
COPY migrations ./migrations
# the import smoke: aslms.cli.main (init, worker, backup, migrate, ops-exporter), aslms.api.main (api),
# aslms.jobs.celery_app (scheduler), kombu.transport.redis, uvicorn.loops.uvloop, and openpyxl and defusedxml
# (`aslms offices import`, design offices-import, decision 21); APP_ENV=test on this line only
RUN pip install --no-cache-dir --no-deps --no-build-isolation . \
 && pip check \
 && APP_ENV=test python -c "import aslms.cli.main, aslms.api.main, aslms.jobs.celery_app, kombu.transport.redis, uvicorn.loops.uvloop, openpyxl, defusedxml" \
 && groupadd --system --gid 10001 aslms \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --no-create-home aslms \
 && mkdir -p /data /backups && chown 10001:10001 /data /backups

USER 10001:10001
CMD ["aslms", "--help"]
