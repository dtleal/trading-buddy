# trading-buddy (backend)

Python 3.12 service. Managed by [uv](https://docs.astral.sh/uv/).
Uses a **flat layout**: packages live directly under `backend/`, imported as
`from core.X import ...`, `from use_cases.X import ...`, etc.

## Layout

```
backend/
├── core/           Domain models, enums, Protocol interfaces. No I/O.
│   ├── models.py       PriceQuote, IntradayBar, IntradayLevels, TradeSetup,
│   │                   BiasReport, DashboardTick, …
│   ├── enums.py        AssetSymbol, BiasLevel, ImpactLevel, SentimentLabel, …
│   └── interfaces.py   Protocols (PricesGateway, CalendarGateway, LLMGateway, …)
│
├── use_cases/      One class per business task; async `execute()`.
│   ├── run_dashboard_tick.py        Orchestrator (one tick = one DashboardTick)
│   ├── compute_*.py                 Technical / macro / sentiment / combined bias
│   ├── compute_intraday_levels.py   Pure: bars → levels (VWAP, EMAs, ATR, swings)
│   ├── detect_trade_setup.py        Pure heuristic: levels + bias → TradeSetup?
│   ├── fetch_*.py                   I/O wrappers around adapters
│   ├── generate_briefing.py         LLM: pre-market briefing
│   └── explain_event.py             LLM: event explainer (pre/post)
│
├── adapters/       External-world implementations.
│   ├── prices_yfinance.py           yfinance: quote + MA200 + intraday bars
│   ├── calendar_forexfactory.py     ForexFactory weekly XML
│   ├── news_rss.py + news_newsapi.py
│   ├── macro_fred.py + macro_fedwatch.py
│   ├── sentiment_keyword.py         Default classifier (no ML deps)
│   ├── cache_redis.py + db_postgres.py
│   └── llm_anthropic.py             Claude API client
│
├── cli/            Typer entry point + Rich renderers.
│   ├── main.py                      `dtb run | brief | explain | snapshot | signal`
│   ├── dashboard.py                 Live dashboard renderer (incl. setup panel)
│   ├── signal_render.py             `dtb signal` panel
│   └── i18n.py                      pt/en strings
│
├── db/             SQLAlchemy schema + Alembic migrations.
├── tests/          unit/ + integration/ (markers: `integration`).
├── container.py    Dependency injection (plain factory).
├── settings.py     pydantic-settings (env-driven config).
├── pyproject.toml  Hatchling build; multi-package wheel.
└── alembic.ini     script_location = db/migrations
```

## Architectural rules

- **Core has no I/O**. `core/models.py` is frozen Pydantic DTOs;
  `core/interfaces.py` is Protocols. Anything that touches HTTP, DB, Redis or
  yfinance is in `adapters/`.
- **Use cases compose adapters via Protocol interfaces**. This is what lets the
  tests run without a real Postgres / Redis / yfinance — they pass fakes that
  implement the same Protocol.
- **Render is separate from compute**. `cli/dashboard.py` and
  `cli/signal_render.py` only know how to turn a domain object into Rich
  panels — they don't run business logic.
- **Pure functions for technical math**. `compute_intraday_levels` and
  `detect_trade_setup` take values in and return values out, no `async` and no
  I/O — they get extensive unit tests.

## CLI commands

```bash
uv run dtb run                                # Live dashboard loop
uv run dtb brief                              # Macro briefing via Claude
uv run dtb explain --event CPI --mode pre     # Event explainer
uv run dtb snapshot --no-prompt               # Tick payload (no LLM)
uv run dtb signal --asset USTEC               # Intraday levels + stop card
```

## Local dev

```bash
uv sync --all-extras                          # install all deps + extras (ml)
uv run dtb --help                             # CLI surface
uv run pytest -m "not integration"            # fast unit tests
uv run black  core adapters use_cases cli db container.py settings.py tests
uv run isort  core adapters use_cases cli db container.py settings.py tests
uv run mypy   core adapters use_cases cli db container.py settings.py
```

See the top-level `Makefile` for shortcuts (`make install`, `make test`,
`make lint`, `make format`, `make typecheck`, `make db-migrate`, etc.).

## Test layout

```
tests/
├── unit/                   No network, no DB. ~60 fast tests.
│   ├── test_compute_*.py       Sub-scores and combined bias
│   ├── test_compute_intraday_levels.py
│   ├── test_detect_trade_setup.py
│   ├── test_fetch_*.py
│   └── test_*_briefing.py / test_explain_event.py
├── integration/            Hit live yfinance/FRED/Postgres/Redis. Marker required.
├── fakes.py                Reusable Protocol stubs.
└── conftest.py             Async test config.
```

Run only unit tests:
```bash
uv run pytest -m "not integration"
```

Run integration (slow, requires `.env` filled and docker stack up):
```bash
uv run pytest -m integration
```
