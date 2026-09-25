FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY aslms ./aslms
RUN pip install -e .

EXPOSE 8000
CMD ["uvicorn", "aslms.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
