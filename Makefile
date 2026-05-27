SHELL := /bin/bash

.DEFAULT_GOAL := help

.PHONY: help install run brief explain snapshot docker-snapshot \
        test test-cov test-integration \
        lint format typecheck db-migrate db-revision \
        docker-build docker-build-backend docker-build-frontend \
        docker-up docker-down docker-logs docker-logs-frontend docker-shell \
        frontend-install frontend-dev frontend-build frontend-lint \
        autostart-install autostart-uninstall autostart-status autostart-run \
        kvm-build kvm-up kvm-down kvm-logs kvm-ps clean

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

snapshot:  ## Dump the current tick payload (no LLM). Pipe into another LLM.
	cd backend && uv run dtb snapshot

docker-snapshot:  ## Same as `snapshot` but runs inside the live container.
	docker compose -f docker/docker-compose.yml exec backend dtb snapshot

# -----------------------------------------------------------------------------
# Quality gates
# -----------------------------------------------------------------------------

test:  ## Unit tests only (fast, no network)
	cd backend && uv run pytest -m "not integration"

test-cov:  ## Unit tests with coverage report
	cd backend && uv run pytest --cov=core --cov=adapters --cov=use_cases --cov=cli --cov=db --cov=api --cov=container --cov=settings --cov-report=term-missing -m "not integration"

test-integration:  ## Integration tests (hit real APIs and live DB/Redis)
	cd backend && uv run pytest -m integration

SRC_DIRS := core adapters use_cases cli db api container.py settings.py

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

docker-build:  ## Build all images (backend + frontend)
	docker compose -f docker/docker-compose.yml build

docker-build-backend:  ## Build only the backend image
	docker compose -f docker/docker-compose.yml build backend

docker-build-frontend:  ## Build only the frontend image
	docker compose -f docker/docker-compose.yml build frontend

docker-up:  ## Start the full stack (backend + frontend + postgres + redis)
	docker compose -f docker/docker-compose.yml --env-file .env up -d

docker-down:  ## Stop and remove containers
	docker compose -f docker/docker-compose.yml down

docker-logs:  ## Follow backend logs
	docker compose -f docker/docker-compose.yml logs -f backend

docker-logs-frontend:  ## Follow frontend logs
	docker compose -f docker/docker-compose.yml logs -f frontend

# -----------------------------------------------------------------------------
# KVM production deploy (side-by-side with polymarket / kalshi)
# -----------------------------------------------------------------------------

KVM_COMPOSE := -f docker/docker-compose.yml -f docker/docker-compose.kvm.yml

kvm-build:  ## Build the trading-buddy images on the KVM box (tb-* containers)
	docker compose $(KVM_COMPOSE) --env-file .env build

kvm-up:  ## Bring the trading-buddy stack up on KVM (frontend :3057, backend :8057)
	docker compose $(KVM_COMPOSE) --env-file .env up -d

kvm-down:  ## Stop the trading-buddy stack on KVM
	docker compose $(KVM_COMPOSE) --env-file .env down

kvm-logs:  ## Follow backend logs on KVM
	docker compose $(KVM_COMPOSE) --env-file .env logs -f backend

kvm-ps:  ## docker compose ps with the KVM overlay (shows tb-* names)
	docker compose $(KVM_COMPOSE) --env-file .env ps

# -----------------------------------------------------------------------------
# Frontend dev (outside Docker)
# -----------------------------------------------------------------------------

frontend-install:  ## npm install in frontend/
	cd frontend && npm install

frontend-dev:  ## next dev (http://localhost:3000, hot reload)
	cd frontend && npm run dev

frontend-build:  ## next build (production bundle)
	cd frontend && npm run build

frontend-lint:  ## eslint
	cd frontend && npm run lint

# -----------------------------------------------------------------------------
# macOS autostart (launchd agent)
# -----------------------------------------------------------------------------

AUTOSTART_LABEL := com.trading-buddy.autostart
AUTOSTART_PLIST := $(HOME)/Library/LaunchAgents/$(AUTOSTART_LABEL).plist
AUTOSTART_SRC := scripts/com.trading-buddy.autostart.plist
REPO_ABS := $(shell pwd)

autostart-install:  ## Install launchd agent: stack comes up at login
	@mkdir -p $(HOME)/Library/LaunchAgents $(HOME)/Library/Logs/trading-buddy
	@sed -e "s|__REPO_DIR__|$(REPO_ABS)|g" -e "s|__HOME__|$(HOME)|g" \
		$(AUTOSTART_SRC) > $(AUTOSTART_PLIST)
	@launchctl unload $(AUTOSTART_PLIST) 2>/dev/null || true
	@launchctl load -w $(AUTOSTART_PLIST)
	@echo "[autostart] installed → $(AUTOSTART_PLIST)"
	@echo "[autostart] logs       → $(HOME)/Library/Logs/trading-buddy/"
	@echo "[autostart] verify     → make autostart-status"
	@echo ""
	@echo "Reminder: open Docker Desktop → Settings → 'Start Docker Desktop"
	@echo "when you log in'. The launchd agent waits up to 3 min for Docker"
	@echo "to come up, but it needs Docker to actually start at login."

autostart-uninstall:  ## Remove launchd agent
	@launchctl unload $(AUTOSTART_PLIST) 2>/dev/null || true
	@rm -f $(AUTOSTART_PLIST)
	@echo "[autostart] removed."

autostart-status:  ## Show launchd agent status + tail of the log
	@launchctl list | grep $(AUTOSTART_LABEL) || echo "[autostart] not loaded"
	@echo "--- last 20 log lines ---"
	@tail -n 20 $(HOME)/Library/Logs/trading-buddy/autostart.log 2>/dev/null || echo "(no log yet)"

autostart-run:  ## Run the autostart script now (smoke test, no reboot needed)
	@TRADING_BUDDY_REPO=$(REPO_ABS) $(REPO_ABS)/scripts/autostart-stack.sh
	@echo "[autostart] manual run done."

docker-shell:  ## Open a shell inside the backend container
	docker compose -f docker/docker-compose.yml exec backend bash

# -----------------------------------------------------------------------------
# Housekeeping
# -----------------------------------------------------------------------------

clean:  ## Remove caches and build artefacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/htmlcov backend/.coverage
