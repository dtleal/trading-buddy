# day-trading-buddy (backend)

Python 3.12 service. Managed by [uv](https://docs.astral.sh/uv/).

## Layout

```
src/day_trading_buddy/
├── core/           Domain models, enums, Protocol interfaces. No I/O.
├── use_cases/      One class per business task; async `execute()`.
├── adapters/       External-world implementations (HTTP, DB, Redis, LLM).
├── cli/            Typer entry point + Rich dashboard.
├── db/             SQLAlchemy schema + Alembic migrations.
├── container.py    Dependency injection (plain factory).
├── scheduler.py    APScheduler wiring (5-min tick).
└── settings.py     pydantic-settings (env-driven config).
```

The presentation layer (CLI today, FastAPI/WebSocket later) is a thin wrapper
over use cases that return structured domain DTOs.

## Local dev

```bash
uv sync --all-extras
uv run dtb --help
uv run pytest -m "not integration"
uv run black src tests && uv run isort src tests && uv run mypy src
```

See the top-level `Makefile` for shortcuts.
