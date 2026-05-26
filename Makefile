SHELL := /bin/bash

.DEFAULT_GOAL := help

.PHONY: help install run brief explain test test-cov test-integration \
        lint format typecheck db-migrate db-revision \
        docker-build docker-up docker-down docker-logs docker-shell clean

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# -----------------------------------------------------------------------------
# Local development (requires `uv` installed: https://docs.astral.sh/uv/)
# -----------------------------------------------------------------------------

install:  ## uv sync (creates .venv and installs all deps)
	cd backend && uv sync --all-extras

run:  ## Start the Rich live dashboard (5-min loop)
	cd backend && uv run dtb run

brief:  ## Generate a macro briefing via Claude
	cd backend && uv run dtb brief

explain:  ## Explain an event. Usage: make explain EVENT=CPI
	cd backend && uv run dtb explain --event $(EVENT)

# -----------------------------------------------------------------------------
# Quality gates
# -----------------------------------------------------------------------------

test:  ## Unit tests only (fast, no network)
	cd backend && uv run pytest -m "not integration"

test-cov:  ## Unit tests with coverage report
	cd backend && uv run pytest --cov=core --cov=adapters --cov=use_cases --cov=cli --cov=db --cov=container --cov=scheduler --cov=settings --cov-report=term-missing -m "not integration"

test-integration:  ## Integration tests (hit real APIs and live DB/Redis)
	cd backend && uv run pytest -m integration

SRC_DIRS := core adapters use_cases cli db container.py scheduler.py settings.py

lint:  ## black --check + isort --check + mypy
	cd backend && uv run black --check $(SRC_DIRS) tests
	cd backend && uv run isort --check-only $(SRC_DIRS) tests
	cd backend && uv run mypy $(SRC_DIRS)

format:  ## Apply black + isort
	cd backend && uv run black $(SRC_DIRS) tests
	cd backend && uv run isort $(SRC_DIRS) tests

typecheck:  ## Run mypy on the source tree
	cd backend && uv run mypy $(SRC_DIRS)

# -----------------------------------------------------------------------------
# Database (Alembic)
# -----------------------------------------------------------------------------

db-migrate:  ## Apply pending Alembic migrations
	cd backend && uv run alembic upgrade head

db-revision:  ## New migration. Usage: make db-revision MSG="add foo"
	cd backend && uv run alembic revision --autogenerate -m "$(MSG)"

# -----------------------------------------------------------------------------
# Docker
# -----------------------------------------------------------------------------

docker-build:  ## Build backend image
	docker compose -f docker/docker-compose.yml build

docker-up:  ## Start backend + postgres + redis
	docker compose -f docker/docker-compose.yml --env-file .env up -d

docker-down:  ## Stop and remove containers
	docker compose -f docker/docker-compose.yml down

docker-logs:  ## Follow backend logs
	docker compose -f docker/docker-compose.yml logs -f backend

docker-shell:  ## Open a shell inside the backend container
	docker compose -f docker/docker-compose.yml exec backend bash

# -----------------------------------------------------------------------------
# Housekeeping
# -----------------------------------------------------------------------------

clean:  ## Remove caches and build artefacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/htmlcov backend/.coverage
