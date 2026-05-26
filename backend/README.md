# trading-buddy (backend)

Python 3.12 service. Managed by [uv](https://docs.astral.sh/uv/).
Uses a **flat layout**: packages live directly under `backend/`, imported as
`from core.X import ...`, `from use_cases.X import ...`, etc.

## Layout

```
backend/
├── core/           Domain models, enums, Protocol interfaces. No I/O.
├── use_cases/      One class per business task; async `execute()`.
├── adapters/       External-world implementations (HTTP, DB, Redis, LLM).
├── cli/            Typer entry point + Rich dashboard.
├── db/             SQLAlchemy schema + Alembic migrations.
├── tests/          unit/ + integration/ (markers: `integration`).
├── container.py    Dependency injection (plain factory).
├── scheduler.py    APScheduler wiring (5-min tick).
├── settings.py     pydantic-settings (env-driven config).
├── pyproject.toml  Hatchling build; multi-package wheel.
└── alembic.ini     script_location = db/migrations
```

The presentation layer (CLI today, FastAPI/WebSocket later) is a thin wrapper
over use cases that return structured domain DTOs.

## Local dev

```bash
uv sync --all-extras                          # install all deps + extras (ml)
uv run dtb --help                             # CLI entry point
uv run pytest -m "not integration"            # fast unit tests
uv run black core adapters use_cases cli db container.py scheduler.py settings.py tests
uv run isort core adapters use_cases cli db container.py scheduler.py settings.py tests
uv run mypy  core adapters use_cases cli db container.py scheduler.py settings.py
```

See the top-level `Makefile` for shortcuts (`make install`, `make test`,
`make lint`, `make format`, `make typecheck`, `make db-migrate`, etc.).
