"""Business logic. Services take a SQLAlchemy `Session`, never an HTTP request, and never call external
systems except through `aslms.integration`. Callers (routers, Celery tasks, CLI) own the transaction."""
