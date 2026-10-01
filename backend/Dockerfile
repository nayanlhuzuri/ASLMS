# ASLMS backend image: the CLI, migrations and (later) the API and workers.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY aslms ./aslms
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir ".[redis]"

CMD ["aslms", "--help"]
