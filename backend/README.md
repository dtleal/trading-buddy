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
│   ├── explain_event.py             LLM: event explainer (pre/post)
│   └── manage_qa.py                 Q&A CRUD: list/create/update/delete
│
├── adapters/       External-world implementations.
│   ├── prices_yfinance.py           yfinance: quote + MA200 + intraday bars
│   ├── calendar_forexfactory.py     ForexFactory weekly XML
│   ├── news_rss.py + news_newsapi.py
│   ├── macro_fred.py + macro_fedwatch.py
│   ├── sentiment_keyword.py         Default classifier (no ML deps)
│   ├── cache_redis.py + db_postgres.py
│   ├── db_qa.py                     Postgres CRUD for the Q&A knowledge base
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
  panels — they don't run business logic. Timestamps render in both UTC and
  Brazil time (`zoneinfo("America/Sao_Paulo")`); past calendar events are
  dimmed and tagged `✓ ENCERRADO`.
- **Pure functions for technical math**. `compute_intraday_levels` and
  `detect_trade_setup` take values in and return values out, no `async` and no
  I/O — they get extensive unit tests.

### Calendar gotcha

The public ForexFactory weekly XML feed
(`https://nfs.faireconomy.media/ff_calendar_thisweek.xml`) publishes times in
**UTC**, not Eastern Time, despite the older docstrings on the web suggesting
otherwise. The parser in `adapters/calendar_forexfactory.py` parses the feed
times directly as UTC — see `tests/unit/test_calendar_forexfactory.py` for the
locked-in cases (CB Consumer Confidence "2:00pm" → 14:00 UTC = 10:00 ET in
EDT). The feed also rate-limits anonymous clients; the adapter logs a
`WARNING` when the response has no `<event>` nodes so we can tell rate-limit
days from quiet calendar days.

### Scalper bot gotcha — it manages *manual* positions too

When the scalper bot is **armed** (`_run_bot` in `api/routes/orderflow.py`), it
manages **every open position on its symbols**, not just the ones it opened
itself. It reads positions straight from MT5 via the collector and has no notion
of who opened them — so a position you open by hand is fair game for its exit
logic.

The non-obvious part is the **reverse** path. Bot-opened trades carry a grid
*region* (`_bot.grid[symbol]`, set only on a bot entry); the reverse first tests
`region_broken(...)`, which only fires when price breaks past the whole grid
region. A **manual** position has *no* grid recorded, so that branch is skipped
and it falls straight to the flow signal's stop-and-reverse — which is
intentionally twitchy: just `MIN_PRINTS = 12` directional prints with a
`REVERSE_LEAN = 0.20` lean against the held side (≈70 % of the recent aggressor
prints on the opposite side). That reads **aggressor order flow on the tape, not
price direction** — so a short can be cut on a brief burst of buy-side prints
even while price is still drifting down. Each symbol triggers independently, so
several manual positions can be closed a few seconds apart rather than at once.

### Raw tape recording — the scalper's backtest input

The ingest route appends every data message the collector pushes (`hello` /
`book` / `trade` / `trades` / `liquidity`) verbatim to
`data/orderflow_tape/tape-YYYY-MM-DD.jsonl` (UTC day, bind-mounted in
docker-compose so it survives rebuilds). This exists because MT5 CFD feeds
cannot rewind synthesized ticks — without the recording there is no history to
replay. A recorded session fed back through the aggregator reproduces the exact
snapshots the bot saw, which is what makes the scalper backtestable. Command
echoes and position/P&L mirrors are deliberately not recorded (a replay
simulates execution itself). Disable by setting `ORDERFLOW_RECORD_DIR=""`.

Backtest a recorded day with `uv run dtb replay data/orderflow_tape/tape-*.jsonl`
(`use_cases/replay_scalper.py`): the same aggregator/signal/policy code as the
live bot, with only order fills simulated. `--lot SYM=..`, `--target`, `--stop`
override the bot knobs; check `--usd-per-point` against the broker's contract
spec before trusting absolute USD numbers.

`uv run dtb sweep tape-*.jsonl` replays the tape once per parameter combination
(`use_cases/sweep_scalper.py`; UPPERCASE axes = scalper constants via
`scalper.tuned()`, lowercase = replay params). Read the per-axis P&L means at
the end and pick values whose whole row is healthy — a value that only wins in
one combo is curve-fitting. Sweeps mutate the scalper globals during a run, so
never sweep inside a process with a live armed bot.

The bot also has a per-symbol hard stop (`symbol_stop_usd` on
`POST /api/orderflow/bot`, default 0 = off): closes one symbol when its
floating loss reaches −N USD, capping the dollar damage of a scaled-in grid
without waiting for the region breach or the whole-session loss stop.

### One flow signal — shown == acted on

`use_cases/trade_signal.py :: compute_flow_signal` produces a **single**
`FlowSignal` per symbol (`enter_long` / `enter_short` / `exit` / `hold`, with a
`reason`, `basis`, and a 0–1 `strength` cue). It is stamped onto every
`OrderFlowSnapshot` in `_stamp_snapshot`, so the **same object** is broadcast to
the dashboard and handed to `_run_bot` — the signal the user sees is exactly the
one the armed bot acts on. It is a consolidation, not a new strategy: it imports
and calls the existing `scalper` (`decide_entry`/`should_reverse`) and
`assess_trade_signals` functions and their constants, never re-declaring a
threshold. The bot reads it via `signal_entry_direction` (flat → explosion-only,
identical to the old `detect_explosion` gate) and `signal_says_reverse`
(`basis == "reversal"`, identical to the old `should_reverse`); the softer
`against`/`exhaustion` exits are **advisory** UI alerts the bot does not trade
on. `strength` is a UI conviction cue only — the bot ignores it.

Closes the bot issues are tagged `origin:"bot"` and persisted to `bot_trades`
with a `reason` (`lock` / `reverse` / `target` / `stop`); manual closes are
never recorded. To diagnose *why* a position was closed, read that `reason`
column rather than guessing. This behaviour is intentional — documented here
because it surprises (manual trades being closed by the bot looks like a bug but
is the armed-bot contract).

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
