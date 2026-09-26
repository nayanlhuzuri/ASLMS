# Common tasks. On Windows run these from Git Bash, or copy the commands.
COMPOSE      = docker compose
COMPOSE_PROD = docker compose -f docker-compose.yml -f docker-compose.prod.yml
API          = $(COMPOSE) run --rm api

.PHONY: up down db migrate seed demo test lint web-dev backfill cycle report prod-up prod-migrate backup

up:            ## dev stack: postgres, redis, api, workers, beat, web
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

db:            ## only the databases
	$(COMPOSE) up -d postgres redis

migrate:
	$(API) alembic upgrade head

seed:
	$(API) aslms seed

demo:          ## development demo data (refused when APP_ENV=prod)
	$(API) aslms seed-demo && $(API) aslms rescore

backfill:      ## ingest cause-list PDFs already in data/causelists
	$(API) aslms backfill

cycle:         ## daily cycle for tomorrow
	$(API) aslms cycle

report:
	$(API) aslms report

test:          ## backend tests (Postgres must be up on POSTGRES_HOST_PORT)
	cd backend && python -m pytest -q   # with backend/.venv activated

lint:
	cd backend && ruff check aslms tests alembic
	cd frontend && npm run lint && npm run typecheck

web-dev:       ## Next.js dev server against the local API
	cd frontend && API_BASE_URL=http://localhost:8000 npm run dev

prod-up:
	$(COMPOSE_PROD) up -d --build

prod-migrate:  ## migrations bypass PgBouncer
	$(COMPOSE_PROD) run --rm -e DATABASE_URL_SYNC=postgresql+psycopg://$${POSTGRES_USER:-aslms}:$${POSTGRES_PASSWORD:-aslms}@postgres:5432/$${POSTGRES_DB:-aslms} api alembic upgrade head

backup:        ## one backup now
	$(COMPOSE_PROD) run --rm backup /backup.sh once
