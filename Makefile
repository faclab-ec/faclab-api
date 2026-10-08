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

lint:  ## Fix linter errors
	source .venv/bin/activate && ruff check --fix . && ruff format .

typecheck:  ## Type check with ty
	source .venv/bin/activate && ty check

migrations:  ## Create a new migration with Alembic
	docker compose run --no-deps --rm api alembic revision --autogenerate -m "$(m)"

upgrade:  ## Apply all pending migrations with Alembic
	docker compose run --no-deps --rm api alembic upgrade head

downgrade:  ## Downgrade the database to the previous migration
	docker compose run --no-deps --rm api alembic downgrade $(d)

seed:  ## Seed the database with test data
	docker compose run --rm api python -m scripts.seed

seed-admin:  ## Bootstrap the initial admin user (idempotent)
	docker compose run --rm api python -m src.auth.seed
