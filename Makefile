# Makefile generated with pymakefile
help:
	@grep -E '^[A-Za-z0-9_.-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "[36m%-30s[0m %s\n", $$1, $$2}'

build:  ## Build the docker image
	docker compose build

start:
	docker compose up -d

dev: 
	docker compose up -d && docker rm -f api && docker compose run --rm -p 3000:3000 api

down:  ## Stop the docker containers
	docker compose down

test:  ## Run tests
	docker compose run --no-deps --rm api pytest --cov='src'

test-integration:  ## Run the Postgres integration tests on a throwaway <db>_test database, with the roles of .env
	docker compose run --rm api sh -c 'DB="$${DATABASE_URL##*/}_test"; \
		TEST_DATABASE_URL="$${DATABASE_URL_ADMIN%/*}/$$DB" \
		TEST_DATABASE_URL_APP="$${DATABASE_URL%/*}/$$DB" \
		TEST_DATABASE_URL_WORKER="$${DATABASE_URL_WORKER%/*}/$$DB" \
		TEST_DATABASE_URL_MIGRATIONS="$${DATABASE_URL_MIGRATIONS%/*}/$$DB" \
		pytest tests/integration/postgres $(args)'

lint:  ## Fix linter errors
	source .venv/bin/activate && ruff check --fix . && ruff format .

typecheck:  ## Type check with ty
	source .venv/bin/activate && ty check

db-roles:  ## Create or update the database roles and the database (idempotent; before `make upgrade`)
	docker compose run --no-deps --rm api python -m src.shared.infra.db_roles

migrations:  ## Create a new migration with Alembic
	docker compose run --no-deps --rm api alembic revision --autogenerate -m "$(m)"

upgrade:  ## Apply all pending migrations with Alembic
	docker compose run --no-deps --rm api alembic upgrade head

downgrade:  ## Downgrade the database to the previous migration
	docker compose run --no-deps --rm api alembic downgrade $(d)

seed:  ## Seed the database with test data
	docker compose run --rm api python -m scripts.seed

seed-admin:  ## Bootstrap the default tenant and its first admin (idempotent)
	docker compose run --rm api python -m src.auth.seed

provision-tenant:  ## Create a tenant and its first admin (idempotent): args="--ruc ... --legal-name ... --admin-username ... --admin-email ..."
	docker compose run --rm -e PROVISION_ADMIN_PASSWORD api python -m src.tenancy.provision $(args)

purge-idempotency-keys:  ## Delete the Idempotency-Key rows older than IDEMPOTENCY_KEY_RETENTION_HOURS (every tenant)
	docker compose run --rm api python -m src.shared.infra.idempotency.purge
