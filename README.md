# day-trading-buddy

Macro context co-pilot for day trading **USTEC (Nasdaq 100), S&P 500 and Gold**.

It is **not** a trading bot. It does not place orders. It gives you a refreshed
read of the macro and news environment every 5 minutes while you trade.

## What it does

- Pulls spot prices and 200-period moving averages for USTEC, SPX, Gold, VIX,
  VIX9D and VIX3M.
- Aggregates today's high-impact US economic events (FOMC, CPI, NFP, PCE, PPI,
  Jobless Claims, etc.) with countdowns.
- Aggregates relevant news headlines and scores their sentiment.
- Tracks macro indicators (Fed funds rate, 10Y yield, DXY, CME FedWatch rate
  probabilities).
- Combines everything into a 0-100 bias score per asset:
  - `>= 60`  BULLISH
  - `<= 40`  BEARISH
  - else     NEUTRAL / RANGE
- Fires an LLM-generated explanation 30 min before any high-impact event and
  again ~2 min after the release (uses Claude API).
- Renders a live Rich terminal dashboard refreshed every 5 minutes.

## Quickstart

```bash
cp .env.example .env
#   fill CLAUDE_API_KEY (required), FRED_API_KEY + NEWSAPI_KEY (optional)

make install         # uv sync inside backend/
make docker-up       # postgres + redis + backend dashboard
make docker-logs     # follow the backend output
```

Manual commands once the stack is up:

```bash
make brief                      # pre-market macro briefing in PT-BR
make explain EVENT=CPI          # pre/post-event explainer
```

## Architecture

```
day-trading-buddy/
├── docker/      Docker images and compose files
├── backend/     Python 3.12 service (uv-managed)
│   └── src/day_trading_buddy/
│       ├── core/        Domain models, enums, interfaces (Protocols). No I/O.
│       ├── use_cases/   One class per business task. Async `execute()`.
│       ├── adapters/    External-world implementations (HTTP, DB, Redis, LLM).
│       ├── cli/         Typer entry point + Rich dashboard.
│       └── db/          SQLAlchemy schema + Alembic migrations.
└── frontend/    Reserved for phase 2 (web UI).
```

Each computation lives in its own use case, wired together by `container.py`.
Adapters are swappable behind Protocol interfaces defined in `core/interfaces.py`.

## Make targets

```
make install            uv sync (installs all backend deps)
make run                Start the live Rich dashboard (5-min loop)
make brief              Pre-market macro briefing via Claude
make explain EVENT=CPI  Explain an upcoming or just-released event
make test               Unit tests (fast, no network)
make test-cov           Unit tests with coverage report
make test-integration   Integration tests (hit real APIs / DB)
make lint               black --check + isort --check + mypy
make format             black + isort (write)
make typecheck          mypy
make db-migrate         Apply pending Alembic migrations
make db-revision MSG=…  Generate a new Alembic migration
make docker-up          docker compose up (backend + postgres + redis)
make docker-down        docker compose down
make docker-logs        Follow backend logs
make clean              Wipe caches and build artefacts
```

## Out of scope (phase 2+)

- Frontend (a `frontend/` placeholder is reserved).
- Telegram / push notifications.
- Real-time VIX put/call ratio and option skew (needs paid CBOE/ORATS data).
- Backtesting of the bias signal vs price.
- Own neural network trained on labelled news.
- Multi-user / authentication.
