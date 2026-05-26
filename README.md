# trading-buddy

Macro context co-pilot for day trading **USTEC (Nasdaq 100), S&P 500 and Gold**.

It is **not** a trading bot. It does not place orders. It gives you a refreshed
read of the macro + intraday environment while you trade, and points out
**high-confluence setups** when (and only when) the data alignment is objectively
favorable.

## What it does

### Macro & sentiment layer (5-min cadence)

- Pulls spot prices and the **daily 200-period** moving average for USTEC, SPX,
  Gold, VIX, VIX9D and VIX3M.
- Aggregates today's high/medium-impact US economic events (FOMC, CPI, NFP,
  PCE, PPI, Jobless Claims, Consumer Confidence…) with countdowns.
- Pulls headlines from RSS (Reuters/CNBC/MarketWatch) and NewsAPI, and scores
  their sentiment with a keyword classifier.
- Tracks macro indicators via FRED (Fed funds, 10Y yield, DXY, CPI, UNRATE)
  plus CME FedWatch implied probabilities.
- Combines everything into a 0-100 **bias score** per asset:
  - `≥ 60`  ALTA   (bullish)
  - `≤ 40`  BAIXA  (bearish)
  - else    LATERAL (range)

### Intraday layer (`dtb signal`, also feeds the dashboard)

- Pulls 5-minute OHLCV bars from yfinance (~15-min delay on free tier).
- Computes deterministic levels: **HOD/LOD**, **VWAP**, **Opening Range**,
  **previous-day OHLC**, **EMA 9/20/50/200**, **SMA 200**, **ATR(14)**, plus
  **5-bar swing pivots** (last swing high and low).
- Suggests **structure-based stops**: stop below the last swing low (LONG) or
  above the last swing high (SHORT), with a 0.5×ATR buffer.
- Position sizing helper when `ACCOUNT_SIZE_USD > 0` (uses NQ/ES/GC contract
  multipliers by default; override with `--multiplier`).

### Setup-with-edge panel (dashboard)

When **multiple objective confluences align**, the dashboard emits a single
panel with the trade idea. Otherwise it explicitly stays silent
("Sem setup com vantagem clara agora").

LONG edge requires **all** of:
- Combined bias score ≥ 60
- Price above EMA 200, SMA 200, AND VWAP on 5m
- A **pullback** present (price within 0.75×ATR of the nearest mean — not chasing)
- A confirmed swing low (stop has structure)
- Risk:reward ≥ 2.0 to the next resistance (PDH / HOD / swing high / 4×ATR cap)

SHORT mirrors that. LATERAL bias (40 < score < 60) is hard-rejected.

The heuristic is conservative by design — **false negatives over false
positives**. The panel will be silent most of the day.

### LLM features (need `CLAUDE_API_KEY`)

- `dtb brief` — pre-market briefing in PT-BR via Claude Opus 4.7.
- `dtb explain --event CPI` — pre or post event explainer.
- `dtb snapshot` — dumps the LLM prompt + tick payload **without calling the
  API**, so you can hand it to another Claude session (e.g. via the
  `/dtb-brief` slash command) and get the same briefing for free.

## Quickstart

```bash
cp .env.example .env
#   - CLAUDE_API_KEY  (required only for brief/explain)
#   - FRED_API_KEY    (optional, ~2 min signup — improves macro panel)
#   - NEWSAPI_KEY     (optional — supplements RSS news)

make install         # uv sync inside backend/
make docker-up       # postgres + redis + backend dashboard
make docker-logs     # watch the dashboard refresh every 10s
```

Manual commands once the stack is up:

```bash
make brief                                     # pre-market macro briefing
make explain EVENT=CPI                         # pre/post-event explainer
make snapshot                                  # tick payload as markdown (no LLM)
docker compose -f docker/docker-compose.yml exec backend \
    dtb signal --asset USTEC                   # intraday levels + stop card
```

### Viewing the dashboard

The container runs `dtb run` and re-renders every `DISPLAY_REFRESH_SECONDS`
(default 10s). The same in-memory tick is reused — fresh data is only
fetched every `TICK_INTERVAL_SECONDS` (default 300s).

Three viewing modes, in order of recommendation:

```bash
make docker-logs                               # safe, full history, easy to exit
docker attach day-trading-buddy-backend-1      # interactive TTY (Ctrl-P Ctrl-Q to exit)
make run                                       # local TTY without container
```

## Architecture

```
trading-buddy/
├── docker/      Docker images and compose files
├── backend/     Python 3.12 service (uv-managed, flat layout)
│   ├── core/         Domain models, enums, interfaces (Protocols). No I/O.
│   ├── use_cases/    One class per business task. Async `execute()`.
│   ├── adapters/     External-world implementations (HTTP, DB, Redis, LLM).
│   ├── cli/          Typer entry point + Rich dashboard + signal renderer.
│   ├── db/           SQLAlchemy schema + Alembic migrations.
│   ├── container.py  Dependency injection (plain factory).
│   └── settings.py   pydantic-settings (env-driven config).
└── frontend/    Reserved for phase 2 (web UI).
```

Imports are top-level: `from core.models import ...`,
`from use_cases.fetch_market import ...`. Each computation lives in its own
use case, wired together by `container.py`. Adapters are swappable behind
Protocol interfaces in `core/interfaces.py`.

### Key use cases

| Use case | Role |
|---|---|
| `run_dashboard_tick` | Orchestrator — fetches everything, runs sub-computations, returns a `DashboardTick`. |
| `compute_technical_bias` / `compute_macro_signal` / `compute_news_sentiment` | Sub-scores (0-100) per asset. |
| `compute_combined_bias` | Weighted sum → final bias score + ALTA/BAIXA/LATERAL label. |
| `compute_intraday_levels` | Pure function: bars → HOD/LOD/VWAP/OR/PDH/EMAs/ATR/swings. |
| `detect_trade_setup` | Pure heuristic: levels + bias → `TradeSetup` or `None`. |
| `generate_briefing` / `explain_event` | LLM use cases (Claude). |

## Make targets

```
make install            uv sync (installs all backend deps)
make run                Start the live Rich dashboard (local, no container)
make brief              Pre-market macro briefing via Claude (paid API)
make explain EVENT=CPI  Explain an upcoming or just-released event (paid API)
make snapshot           Print the tick payload markdown (no LLM, no cost)
make test               Unit tests (fast, no network)
make test-cov           Unit tests with coverage report
make test-integration   Integration tests (hit real APIs / DB)
make lint               black --check + isort --check + mypy
make format             black + isort (write)
make typecheck          mypy
make db-migrate         Apply pending Alembic migrations
make db-revision MSG=…  Generate a new Alembic migration
make docker-build       Build the backend image
make docker-up          docker compose up (backend + postgres + redis)
make docker-down        docker compose down
make docker-logs        Follow backend logs (recommended view mode)
make docker-snapshot    Run `dtb snapshot` inside the live container
make clean              Wipe caches and build artefacts
```

## CLI commands (`dtb`)

```
dtb run                              Live dashboard loop (default container CMD)
dtb brief                            Macro briefing via Claude
dtb explain --event CPI [--mode pre|post]
dtb snapshot [--with-prompt|--no-prompt]   Tick payload, no LLM
dtb signal --asset USTEC|SPX|GOLD          Intraday levels + structure stop
    [--interval 5m] [--lookback 5]
    [--risk-pct 2.0] [--account-size 50000] [--multiplier 20]
```

## Tunable knobs (`.env`)

```
# Cadence
TICK_INTERVAL_SECONDS=300          Data fetch interval (5 min)
DISPLAY_REFRESH_SECONDS=10         Screen redraw interval (no API cost)

# Bias scoring
BIAS_WEIGHT_TECHNICAL=0.40         Must sum to 1.0
BIAS_WEIGHT_MACRO=0.30
BIAS_WEIGHT_SENTIMENT=0.30
BIAS_THRESHOLD_BULLISH=60
BIAS_THRESHOLD_BEARISH=40

# Day-trade signal
ACCOUNT_SIZE_USD=0                 Set > 0 to enable position sizing
RISK_PER_TRADE_PCT=2.0
STOP_BUFFER_ATR_MULTIPLE=0.5
OPENING_RANGE_MINUTES=30

# LLM models
ANTHROPIC_MODEL_BRIEFING=claude-opus-4-7
ANTHROPIC_MODEL_CLASSIFIER=claude-haiku-4-5-20251001
```

## Avoiding Anthropic API charges with `/dtb-brief`

The bot ships a Claude Code slash command at
`~/.claude/commands/dtb-brief.md` (not in the repo). When you type
`/dtb-brief` in your Claude session, it:

1. Runs `dtb snapshot --no-prompt` inside the container (free — yfinance/FRED).
2. Reads the markdown payload (the same data `dtb brief` would send to Claude).
3. Generates the briefing in **the current Claude session** instead of via the
   paid `CLAUDE_API_KEY` flow.

Same model (Opus 4.7), zero Anthropic API spend.

## Limitations & honest caveats

- **yfinance free tier has ~15-min lag** on intraday data — `dtb signal` is a
  pre-trade checklist, NOT a real-time execution signal.
- The trade-setup detector is a **heuristic**, not a forecast. It refuses to
  emit a setup when conditions are mixed; an emitted setup still doesn't
  guarantee profit.
- ^NDX / ^GSPC are **cash indices**, not futures (NQ/ES) — numbers will differ
  by basis. Confirm execution levels on your broker.
- The post-event explainer doesn't auto-fire yet (was originally planned for
  30 min before high-impact events). Run `dtb explain` manually for now.

## Out of scope (phase 2+)

- Frontend (a `frontend/` placeholder is reserved).
- Telegram / push notifications.
- Real-time VIX put/call ratio and option skew (needs paid CBOE/ORATS data).
- Backtesting of the bias signal vs price.
- Auto-fire of LLM explainers around scheduled events.
- Multi-user / authentication.
