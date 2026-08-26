# trading-buddy

Macro context co-pilot for day trading the six FTMO instruments **USTEC
(Nasdaq 100), USA500 (S&P 500), GOLD, US30 (Dow Jones), GER40 (DAX 40) and
EURUSD**.

Two surfaces:
- **CLI dashboard** (`dtb run`) — Rich-based terminal view, same data, no browser needed.
- **Web app** (`http://localhost:3000`) — Next.js 15 frontend with live VIX chart and configurable VIX alerts. See [`frontend/README.md`](frontend/README.md).

At its core it is a **read-only co-pilot**: a refreshed read of the macro +
intraday environment while you trade, pointing out **high-confluence setups** when
(and only when) the data alignment is objectively favorable.

It also has an **optional, opt-in order-flow execution layer** (off by default):
a profit-target auto-close, a per-asset "fechar tudo" button, and a deterministic
explosion-scalper bot that opens and closes positions. Execution requires explicit
local gates on the collector (`allow_auto_close` / `allow_auto_trade`) and the bot
only opens on a **demo** account. See [`collector/README.md`](collector/README.md).
It is **not** a proven money-maker — the bot is a tunable mechanism to forward-test
on demo, not financial advice. To validate it on data instead of vibes, the ingest
records every collector message to `data/orderflow_tape/` (JSONL per UTC day) and
`dtb replay` / `dtb sweep` backtest the exact live decision code over those
recordings — see "Raw tape recording" in [`backend/README.md`](backend/README.md).

## What it does

### Tracked assets

Six instruments, in screen order. The `backend` name is what the code and the
API use; the `MT5` name is how FTMO spells it, which is what you see on your
chart:

| backend | UI label | MT5 (FTMO) | Yahoo (daily / intraday) |
|---|---|---|---|
| `USTEC` | USTEC | `US100.cash` | `^NDX` / `NQ=F` |
| `SPX` | USA500 | `US500.cash` | `^GSPC` / `ES=F` |
| `GOLD` | GOLD | `XAUUSD` | `GC=F` |
| `US30` | US30 | `US30.cash` | `^DJI` / `YM=F` |
| `GER40` | GER40 | `GER40.cash` | `^GDAXI` |
| `EURUSD` | EURUSD | `EURUSD` | `EURUSD=X` |

Bitcoin, USOIL and US2000 were dropped — Bitcoin to free up screen space, the
other two because their round-trip cost (spread plus commission) is huge next to
how far they travel in a day: 1.7% and 2.3% of the average daily range, against
0.24% on US100. Their `AssetSymbol` members are deliberately kept in the enum so snapshots
saved before the change still load, but nothing tracks them any more.

**To add or remove an instrument**, edit `TRACKED_ASSETS` in
`backend/core/enums.py` and the matching table in `frontend/lib/types.ts`. Four
other places also need an entry, and `tests/unit/test_tracked_assets.py` fails
loudly if you miss one:

- `YAHOO_TICKERS` (+ `INTRADAY_TICKERS` for a cash index) in `prices_yfinance.py`
- `_DEFAULT_LOTS` in `api/routes/orderflow.py` — a symbol missing here is
  **skipped by the scalper bot** entirely
- `DEFAULT_LOTS` / `DEFAULT_USD_PER_POINT` in `replay_scalper.py`
- `ORDERFLOW_SYMBOLS` in `.env`, plus a `symbols[]` mapping in the collector's
  `config.json` (see [`collector/README.md`](collector/README.md))

### Macro & sentiment layer (5-min cadence)

- Pulls spot prices and the **daily 200-period** moving average for USTEC, SPX,
  GOLD, US30, GER40, EURUSD, VIX, VIX9D and VIX3M.
- Aggregates today's high/medium-impact US economic events (FOMC, CPI, NFP,
  PCE, PPI, Jobless Claims, Consumer Confidence…) with countdowns. Each event
  is shown in both **UTC and Brazil time (BRT)**; events already released are
  dimmed and marked **✓ ENCERRADO** (with the actual print if the source
  provided one).
- Pulls headlines from RSS (Reuters/CNBC/MarketWatch) and NewsAPI, and scores
  their sentiment with a keyword classifier.
- Tracks macro indicators via FRED (Fed funds, 10Y yield, DXY, CPI, UNRATE)
  plus CME FedWatch implied probabilities.
- Combines everything into a 0-100 **bias score** per asset:
  - `≥ 60`  ALTA   (bullish)
  - `≤ 40`  BAIXA  (bearish)
  - else    LATERAL (range)

### Intraday layer (`dtb signal`, also feeds the dashboard)

- **Bar source: MT5 first, Yahoo as fallback.** When the collector is feeding,
  the dashboard tick reads the broker's own **M5 bars** (`latest_candles()` in
  the order-flow route, up to 2000 bars ≈ 7 days). They are the same candles
  the trader has on screen, they arrive live instead of ~15 minutes late, and
  they carry **MT5 tick volume** — which is what makes **VWAP** work at all on
  EURUSD and GER40, where Yahoo reports zero volume. A symbol with fewer than
  `MIN_MT5_BARS` (400) bars stored falls back to Yahoo, so the tick still works
  with the collector down. `dtb signal` always reads Yahoo (it runs without a
  collector).
- Yahoo fallback: pulls 5-minute OHLCV bars (~15-min delay on free tier).
  Intraday bars for the cash indices (**USTEC / SPX / US30**) come from
  the continuous **futures** (`NQ=F` / `ES=F` / `YM=F`), not the cash
  index (`^NDX` / `^GSPC` / `^DJI`). GOLD is already a future (`GC=F`) and EURUSD
  quotes ~24h anyway. GER40 has no continuous DAX future on Yahoo, so it stays on
  `^GDAXI` and its 5m bars only cover the Xetra session. The cash indices only
  print during RTH (~77 bars/day), so a 200-bar 5m MA reaches back ~2.5 trading
  days and won't match the near-24h instrument a trader actually watches
  (futures: ~213 bars/day → 200 bars ≈ 0.7 day). Spot quotes and the daily
  MA200 still use the cash index; see `INTRADAY_TICKERS` in `prices_yfinance.py`.
- Computes deterministic levels: **HOD/LOD**, **VWAP**, **Opening Range**,
  **previous-day OHLC**, **EMA 9/20/50/200**, **SMA 200**, **ATR(14)**, plus
  **5-bar swing pivots** (last swing high and low).
- Suggests **structure-based stops**: stop below the last swing low (LONG) or
  above the last swing high (SHORT), with a 0.5×ATR buffer.
- **Standard 5m read** surfaced per asset in the UI ("Níveis 5m" panel): price
  vs **VWAP**, **EMA 200** and **SMA 200**. When the two 200s converge (gap
  < 0.1×ATR) they flag **lateral/range**; price clearly above/below both flags
  trend. Computed for every tracked asset (USTEC, SPX, GOLD, US30, GER40,
  EURUSD).
- Position sizing helper when `ACCOUNT_SIZE_USD > 0` (uses NQ/ES/GC contract
  multipliers by default; override with `--multiplier`).

### Breakout detector (5m / 15m / 30m / 60m / 4h)

A Donchian-channel breakout scanner runs on every tick across all six tracked
assets, on five timeframes (5m / 15m / 30m / 60m / 4h — all resampled
in memory from a single 5m fetch per asset, no extra yfinance calls).
5m is included because the user trades on the 5m chart; the filters below
keep noise low enough that even 5m signals are tradable references.
A signal fires only when **all** of the following hold on the candidate bar:

1. **Fresh Donchian cross**: `close > max(high)` of the last 20 bars
   (or symmetric for down breakouts), AND the previous bar's close was
   still inside the channel (not a continuation).
2. **Range expansion**: `bar_range > 1.3 × ATR(14)` — filters wicks.
3. **Close decisive**: the close itself, not just the wick, is past
   the level.
4. **Pre-squeeze (quality flag, off by default)**: `ATR(14)` on the bar
   **before** the break was at most equal to the 20-bar SMA of ATR — i.e.
   volatility was contracting right before the move. This **used to be
   a hard requirement** (filtered out roughly 60% of signals) but it
   misses the most actionable cases — violent reversals that happen in
   already-volatile sessions, like a strong morning rally fading hard
   into the afternoon. Default is now `False`: every Donchian break
   meeting conditions 1-3 fires; the `squeeze` boolean is still computed
   honestly and shown as a ⭐ badge on the panel so you can tell the
   "coil + explosion" setups apart from the "vol begets vol" continuations.

   To restore the original strict behavior, set `BREAKOUT_REQUIRE_SQUEEZE=true`
   in `.env`.

Each signal has a stable `id` (sha1 of asset/timeframe/direction/bar_ts)
so the frontend can dedup alerts across the many ticks that carry the
same recent-breakouts list. The frontend panel offers timeframe + asset
filters, and the alert engine fires a toast + optional browser
notification when a new id appears.

Thresholds live in `backend/use_cases/detect_breakout.py:BreakoutThresholds`.
Set `require_squeeze=False` to fire on any Donchian break that meets
conditions 1-3 (more signals, more noise).

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

### Perfil do Dia — movement-potential / liquidity gate (dashboard + push)

A banner at the top of the dashboard answers one question: **does today promise
real movement, or is it a thin/chop trap** (the kind of day where a few opening
candles move, then participation collapses and offsetting candles bleed the
account). It produces a 0-100 **movement-potential** score and a discrete regime
— `EXPANSÃO` / `NORMAL` / `FRACO` — recomputed **every 5-minute tick**, so it is
dynamic and can change through the session.

Inputs combine structural signals (known at/near the open) with live MT5 data:
- **Bank holiday** in USD (ForexFactory) — the strongest thin-session signal;
  index cash markets are closed so CFD liquidity craters.
- **Scheduled high-impact catalysts** today (and whether any is still upcoming).
- **VIX regime** (compressed vol → smaller ranges; high vol → bigger).
- **Opening-range compression** vs ATR (skipped on holidays — index bars stale).
- **MT5 activity** (when the collector feeds it): today's tick **volume** and
  session **range** vs the same-time-of-day median of the trailing ~20 sessions.
  The *worse* of the two drives the verdict.

Each flow column also carries a per-asset **activity gauge** above its pressure
bar: a real-time candle-size + volume read straight off the live footprint (no
baseline needed, fills the instant flow arrives), with the "% do normal" layer
added once the collector's baseline is in. See `collector/README.md`.

Four blocks of the flow strip are **off by default** and each has its own
on/off button in the card header: **Posições** (the "Posição aberta (MT5)"
detail block), **Sinal do fluxo** (entry/exit read), **Bid · Ask** (the
real-time bid/ask chart) and **Footprint · Tape**.
Off means the block is not rendered at all, so the six columns stay short enough
to read without scrolling; the components are untouched and come straight back
when you switch a button on. Each choice is remembered per browser
(`localStorage`, keys `orderflow.show*`). The P&L card with Breakeven / Fechar
tudo is always visible.

The verdict is pushed to your phone once per day (and again if the regime
genuinely changes mid-session) — see [phone push](#phone-push-notifications-ntfysh).

### VIX × Preço — per-asset stance from the VIX path vs the 5m tape (dashboard + push)

A panel under the VIX chart that turns "where is implied vol and what is the 5m
chart doing" into a **per-asset playbook**, recomputed every 5-minute tick by
`assess_vix_price` (pure, unit-tested). Per asset it emits:

- **`stance`** — the standing read: `VENDER REPIQUE` (sell rallies), `COMPRAR
  RECUO` (buy dips), `FICAR DE FORA` (stay out) or `NEUTRO`.
- **`trigger`** — flips on when price is AT the actionable Bollinger(20,2) band
  *right now* (the "zona de VENDA/COMPRA agora" moment). Pulses in the UI.
- **`caution`** — divergence reads that argue for **closing open positions**:
  price rising WITH the VIX rising (fragile rally → `ENCERRAR COMPRAS`), price
  falling with the VIX bleeding off (selloff losing fuel → `ENCERRAR VENDAS`).

The matrix it encodes: VIX spiking near the top of its 2-day range → don't buy,
sell the rally into the upper band; VIX drifting up while price grinds down in
small overlapping candles between the bands → sell the tops of that range; VIX
rolling over from a spike → relief, buy pullbacks; VIX low and dead-flat with
squeezed bands and overlapping candles → no energy, stay out. **Gold is treated
as the risk-off asset** — a rising VIX supports it, so the direction is
inverted (and the rationale says so).

Inputs: VIX 5m bars (yfinance, 2-day lookback: trend over ~1h, spike over
~30 min, position in the recent range) × each asset's 5m bars already fetched
for the breakout scan (SMA20 slope, candle body/overlap quality, %B and band
width vs its own recent median). Alerts fire as browser toast/sound/desktop
notification on stance changes and zone triggers (edge-triggered, no storm on
reload) and as **ntfy pushes** (stance changes dedup'd on state in Redis; zone
triggers re-arm every 30 min).

### Saldo da conta — per-trade balance/equity curve (dashboard)

A card above the VIX chart showing the account's value over time, styled like
the VIX chart: a single **baseline area** — green above the period's opening
balance (in profit), red below — with a dashed guide-line at that opening.

- **The curve** is reconstructed from the broker's **DEAL history** (`GET
  /api/orderflow/balance/history`), so it covers **every closed trade — manual
  AND bot** (not just the bot; the DB only records bot trades). One step per
  trade, each carrying that trade's realized net; the running balance is
  anchored so the last step equals the account's current balance.
- **The tip** is the live **equity** (balance + floating P&L of open positions),
  so the final segment moves with the open trade. Header shows equity, the
  period P&L vs opening, and the floating gap.
- **Source:** the collector reads `account_info()` (balance/equity) and rebuilds
  the deal-history curve on its ~30s account push (`balance_history` message).
  The backend keeps the steps in memory (re-derived each push) and persists the
  live equity samples to `data/account_balance/` (JSONL per UTC day) so the
  intraday equity wiggle survives a restart.

### Bandas — Bollinger projection tab (`/bands`)

A tab next to Q&A with one 5m candle chart per tracked asset (6 charts,
lightweight-charts), drawn from the **MT5 candles the collector pushes** — the
same feed the trader's own chart shows, not delayed yfinance data. Three charts
per row on a wide screen (two from `md`, one on a phone), on the same 2100px
container the Dashboard uses.

- **Bands:** standard Bollinger (20-period SMA ± 2σ on closes), solid lines.
- **Caminho típico do preço (sky, dashed) + cone:** where price actually went
  the last times it sat at this same spot inside the band. Every past bar with
  the same `%B` (position within the band, ±0.12) is an analog; the next hour
  (12 bars) of each is read, normalised by the band width of the time, and the
  median becomes the route while the 25–75% range becomes the dotted cone
  (`use_cases/project_band_path.py`, `GET /api/orderflow/bands`). Fewer than 12
  analogs → nothing is drawn, on purpose. **This is the symbol's own past
  behaviour, not a forecast.**
- **Band continuation (dashed):** the three band lines carried forward over the
  same horizon, recomputed with the route as the assumed future closes — so the
  bands and the price path never rest on two different assumptions. With no
  measured route it falls back to a drift extrapolation
  (`frontend/lib/bollinger.ts`).
- **Seta ▲/▼ com % (qual banda primeiro):** the share of those past visits that
  reached the **upper** band before the **lower** one. Grey = coin flip (≤55%).
  Before enough history is stored it falls back to a closed-form first-passage
  estimate (random walk with the recent drift and volatility); the tooltip says
  which one you are reading. Price already at or past a band shows **"na
  banda"** instead of a fake 100% — that is where price *is*, not a probability.
- **Pressão (compra · venda):** the Dashboard's live pressure bar, in every
  chart header. Same `PressureGauge` component on the same `/ws/orderflow`
  feed, so the two tabs cannot disagree. It completes the read: the arrow is
  what price *did* the last times it sat here, the bar is who is leaning on the
  tape *right now* — agreement strengthens the case, disagreement is a fight
  worth waiting out.
- **Both badges also on the Dashboard:** the ▲/▼ % arrow and the ↩ % média
  badge also sit inside the **Pressão** block of every column in the Dashboard
  flow strip — same component (`components/bands/BandOddsBadges.tsx`) on the
  same 5s `GET /api/orderflow/bands` poll, so the two tabs cannot disagree.
  There is no candle fallback there: no scenario from the backend, no badge.
  They sit next to the pressure bar on purpose — what price did the other times
  it stood here, right beside who is leaning on the tape now.
- **Selo ↩ % média (volta pra média):** a second badge beside the arrow, shown
  **only when price is sitting at a band** (`%B` ≤ 0.2 or ≥ 0.8) — mid-band the
  question is meaningless, price is already at the middle. It reads: of the
  past visits to this band **in this same market state**, how many got back to
  the middle band within the hour. **Read it upwards: a HIGHER number means it
  is more likely to snap back; a low one means it usually keeps going** (a
  break, not a bounce). Sky = usually comes back, amber = usually
  keeps going (a break, not a bounce), grey = coin flip; dimmed when the sample
  is under 25. Sample size, the conditions held, the typical number of candles
  and the unconditioned figure all live in the tooltip, so the card stays
  glanceable. The state is three readings, all normalised by the band's own
  width so they mean the same thing on GOLD and on US30, shown as chips:
  - **trend** — how far the middle band travelled over the last 5 bars;
  - **width** — today's band width against its 50-bar baseline (the "as bandas
    estão alargando?" test);
  - **push** — one outsized candle (≥1.8× the normal size) driving one way.

  Conditioning costs sample size, so the filter is relaxed in a fixed order
  (push → trend → width) until the sample is usable, and the tooltip names what
  it actually held constant.
- **Why width is the last filter dropped** (measured over ~5 days of live bars,
  from a band touch): the bands' width is by far the strongest signal —
  **52%** get back to the middle while the bands are **squeezing** against
  **28%** while they are **expanding**. The trend is second (55% vs 37% off the
  lower band) and a single big candle is the weakest. The thresholds are
  calibrated on those same live distributions, not guessed, so all three
  buckets stay populated.
- **A honest finding, measured on live data:** going band-to-band inside an
  hour is **rare — roughly 8–15%**. What actually happens is a return to the
  **middle** band (the SMA20), which is why the summary line leads with that
  number. The round trip is not decided by mean reversion but by how wide the
  band is against how fast the market moves: a band ~18 typical bar-moves wide
  simply cannot be crossed in 12 bars. Both numbers are shown with their sample
  size `n`, because a percentage without one is not worth reading.
- **Data path:** collector pushes the last 120 M5 bars per symbol every ~5s for
  the chart, plus a 1500-bar backfill every 10 min and on every reconnect for
  the statistics (`candles` message, bar times converted to true UTC) → the
  backend **merges pushes by bar timestamp** into ~7 days of history →
  `GET /api/orderflow/candles?limit=120` (chart) and `GET /api/orderflow/bands`
  (scenario) — **both polled every 5s**. The last bar is the one still forming,
  so the chart AND the badges move with the live price: the spot in the band
  (`pct_b`) is read off that forming bar, so a slower poll on the scenario left
  the badges a minute behind on a fast move (price already past the middle band
  while the badge still pointed at the band it came from).

### LLM features (need `CLAUDE_API_KEY`)

- `dtb brief` — pre-market briefing in PT-BR via Claude Opus 4.7.
  **Dual-lens by design** — the system prompt now demands per-asset
  sections covering both the daily-structural view (price vs MA200d)
  and the 5m intraday view (VWAP/EMAs/SMA200/PDH/PDL/recent breakouts),
  plus an explicit ✅ convergence / ⚠️ divergence flag. The trader
  on a 5m chart immediately sees when macro and tape disagree.
- `dtb explain --event CPI` — pre or post event explainer.
- `dtb snapshot` — dumps the LLM prompt + tick payload **without calling
  the API**. The payload now includes four sections:
  - `## Market snapshot (daily structural)` — quotes + MA200d
  - `## Intraday (5m) per asset` — full per-asset 5m levels
  - `## Recent breakouts` — pre-computed signals across all 5 timeframes
  - macro + events + headlines (unchanged)

  Hand any of this to another Claude session (e.g. via the `/dtb-brief`
  slash command at `~/.claude/commands/dtb-brief.md`) for a free
  briefing equivalent to the paid `dtb brief`.

### Q&A knowledge base (web app)

A **Q&A tab** in the frontend (`/qa`) is a personal trading playbook: a
searchable list of question/answer pairs you curate over time (e.g. *"vale a
pena operar lateralidade na Bollinger?"*). Answers are stored as **markdown**
and rendered the same way as the briefing. You can add, edit (inline), delete,
filter by free-text or tag, and entries are sorted most-recently-updated first.

Entries live in the `qa_entries` Postgres table and are served by a small CRUD
API (`/api/qa`, see [Backend HTTP surface](#backend-http-surface-for-the-frontend)).
The first entry — the Bollinger/lateralidade answer that started the feature —
is seeded by migration `0002`, so a fresh database starts with it.

## Quickstart

```bash
cp .env.example .env
#   - CLAUDE_API_KEY  (required only for brief/explain)
#   - FRED_API_KEY    (optional, ~2 min signup — improves macro panel)
#   - NEWSAPI_KEY     (optional — supplements RSS news)

make install         # uv sync inside backend/
make docker-up       # postgres + redis + backend + frontend
make docker-logs     # watch the dashboard refresh every 10s
```

Open the web UI:

```
http://localhost:3000   # live VIX chart + alerts + asset overview
http://localhost:8000/health   # backend liveness probe
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
├── docker/      Docker images and compose files (backend + frontend)
├── backend/     Python 3.12 service (uv-managed, flat layout)
│   ├── core/         Domain models, enums, interfaces (Protocols). No I/O.
│   ├── use_cases/    One class per business task. Async `execute()`.
│   ├── adapters/     External-world implementations (HTTP, DB, Redis, LLM).
│   ├── cli/          Typer entry point + Rich dashboard + signal renderer.
│   ├── api/          FastAPI app (REST + WebSocket) for the frontend.
│   ├── db/           SQLAlchemy schema + Alembic migrations.
│   ├── container.py  Dependency injection (plain factory).
│   └── settings.py   pydantic-settings (env-driven config).
└── frontend/    Next.js 15 web app (TypeScript + Tailwind 4).
    ├── app/          App Router pages (/ dashboard, /qa) + providers
    ├── components/   ui/, shared/, vix/, qa/ — panels per feature
    ├── hooks/        useLiveTick, useVixAlerts, useQA
    └── lib/          api.ts, ws.ts, types.ts, alerts/{store,engine,notify}
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
| `assess_day_outlook` | Pure gate: calendar + VIX + opening range + MT5 activity → `DayOutlook` (score/regime). |
| `assess_vix_price` | Pure matrix: VIX 5m path × asset 5m tape (trend, candle quality, Bollinger) → per-asset `VixPriceSignal` (stance/trigger/caution). |
| `aggregate_orderflow` | Rolling DOM/footprint/tape state + real-time `LiveActivity` per symbol. |
| `assess_trade_signals` | Pure: open position + flow lean → in-trade alerts (pressure-against / take-profit). |
| `autoclose` / `scalper` | Pure decision logic for the opt-in execution layer: whole-account profit-target close, and the explosion-scalper bot's entries (`detect_explosion` / `decide_entry`), reversal (`should_reverse`) and gating (`should_open`). Demo-gated; off by default. |
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
make docker-build         Build all images (backend + frontend)
make docker-build-backend Build only backend image
make docker-build-frontend Build only frontend image
make docker-up            docker compose up (backend + frontend + postgres + redis)
make docker-down          docker compose down
make docker-logs          Follow backend logs (recommended view mode)
make docker-logs-frontend Follow frontend logs
make docker-snapshot      Run `dtb snapshot` inside the live container
make frontend-install     npm install in frontend/
make frontend-dev         next dev (http://localhost:3000, hot reload)
make frontend-build       next build (production bundle)
make frontend-lint        eslint
make clean                Wipe caches and build artefacts
```

## CLI commands (`dtb`)

```
dtb run                              Live dashboard loop (default container CMD)
dtb brief                            Macro briefing via Claude
dtb explain --event CPI [--mode pre|post]
dtb snapshot [--with-prompt|--no-prompt]   Tick payload, no LLM
dtb signal --asset USTEC|SPX|GOLD|US30|GER40|EURUSD
                                           Intraday levels + structure stop
    [--interval 5m] [--lookback 5]
    [--risk-pct 2.0] [--account-size 50000] [--multiplier 20]
dtb replay data/orderflow_tape/tape-*.jsonl   Backtest the scalper on a recorded tape
    [--target 350] [--stop 900] [--lot SYM=2.0] [--usd-per-point SYM=1.0] [--detail]
dtb sweep tape-*.jsonl [--set NAME=v1,v2]     Parameter sweep over a tape; per-axis
    [--top 10]                                P&L means expose robust regions
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
- The **ForexFactory weekly XML feed rate-limits anonymous clients** — when
  that happens the calendar panel says "Sem eventos relevantes" and a
  `WARNING` is emitted. The 1-hour Redis cache (`CACHE_TTL_SECONDS`) softens
  the issue; events return as soon as the limit clears.
- The post-event explainer doesn't auto-fire yet (was originally planned for
  30 min before high-impact events). Run `dtb explain` manually for now.

## Deployment on the shared KVM (side-by-side with polymarket / kalshi)

The same Hostinger KVM box also hosts `polymarket_trader` (`poly-*`) and
`kalshi_trader` (`kal-*`). Trading-buddy installs **without touching either**:

- Containers are renamed `tb-backend`, `tb-frontend`, `tb-postgres`, `tb-redis`
- Host ports move out of the way (frontend **3057**, backend **8057**;
  postgres + redis kept internal only)
- Docker network + volumes are prefixed `trading-buddy-*`
- The Compose project name is forced to `trading-buddy`

The trick: a thin override file `docker/docker-compose.kvm.yml` renames the
containers + volumes, and the base `docker-compose.yml` picks host ports up
from `BACKEND_PORT` / `FRONTEND_PORT` env vars (with the local defaults
8000 / 3000 preserved).

### One-time setup

```bash
ssh kvm  # alias for root@72.62.15.111
cd /root
git clone git@github.com:dtleal/trading-buddy.git
cd trading-buddy
cp .env.example .env
# edit .env, set BACKEND_PORT=8057 and FRONTEND_PORT=3057,
# plus any API keys (CLAUDE_API_KEY, FRED_API_KEY, NEWSAPI_KEY, NTFY_TOPIC)
make kvm-build
make kvm-up
make kvm-ps
```

After this the dashboard is reachable at `http://72.62.15.111:3057`.

### Updates

Slash command `/update-kvm-trading-buddy-prod` (Claude Code) handles the
pull + rebuild + verify cycle, including a check that `poly-*` and `kal-*`
containers are still present and untouched after the deploy.

Manual equivalent:

```bash
ssh kvm "cd /root/trading-buddy && git pull origin main && make kvm-build && make kvm-up"
```

### Troubleshooting (lessons from the first prod cutover)

**Dashboard stuck on "Aguardando primeiro tick…" despite healthy backend.**
Open DevTools → Console. If you see
`SyntaxError: ... "delta_1d":NaN ... is not valid JSON`, the backend is
emitting `NaN` somewhere. JS `JSON.parse` rejects `NaN` (Python's accepts it
silently — so backend tests stay green while the browser crashes). Fix at
the source: convert NaN/Inf to `None` before storing in any Pydantic field.
There's already a `_clean_float` helper in `adapters/macro_fred.py` to copy.

**Frontend on a public IP refuses to call the API (CORS).**
The default allowlist covers `localhost`, `127.0.0.1`, `*.local`, and
RFC1918 LAN ranges via a regex. **Public IPs need to be added explicitly**
via `CORS_EXTRA_ORIGINS` in `.env`. Comma-separated. Example:

```
CORS_EXTRA_ORIGINS=http://72.62.15.111:3057,https://app.example.com
```

**Frontend bundle hits the wrong backend port.**
The Next.js bundle bakes `NEXT_PUBLIC_API_URL` at build time. If empty, the
runtime falls back to `${window.location.hostname}:8000` — wrong on KVM
where the backend is on 8057. Always rebuild the frontend image whenever
the backend port changes:

```bash
ssh kvm "cd /root/trading-buddy && docker compose -f docker/docker-compose.yml -f docker/docker-compose.kvm.yml --env-file .env build --no-cache frontend && docker compose -f docker/docker-compose.yml -f docker/docker-compose.kvm.yml --env-file .env up -d frontend"
```

Override the baked URL via `KVM_FRONTEND_API_URL` in `.env` if the host's
public IP ever changes.

**Browser shows old behavior after deploy.**
Next.js serves chunks with `Cache-Control: s-maxage=31536000` and content-
hashed filenames. The browser should pick up new chunks automatically, but
service workers and stale HTML can hold on. Order of escalation:
1. Hard refresh: `Cmd + Shift + R` (or `Ctrl + Shift + R`).
2. Anonymous / private window — bypasses cache + service workers.
3. DevTools → Application → Storage → "Clear site data".

**Polymarket / kalshi must not be impacted by a trading-buddy deploy.**
After every `make kvm-up` / `kvm-build`, verify with:

```bash
ssh kvm "docker ps --format '{{.Names}}' | grep -E '^(poly|kal)-' | sort | wc -l"
```

The count must match what existed before the deploy (currently 7 for
polymarket, 0 for kalshi while stopped). Container IDs and uptimes should
also be unchanged — those are stronger evidence than a name count alone.

## Phone push notifications (ntfy.sh)

The backend can push every new breakout signal to your phone via
[ntfy.sh](https://ntfy.sh), so you get alerts even with the browser
closed and the screen locked. Free, no account, no SMS.

### One-time setup (~2 minutes)

1. **Install the ntfy app** on your phone (App Store / Play Store, free).
2. **Pick a secret topic name** — any unique string. Treat it like a
   password (anyone who guesses it can read your alerts). E.g.
   `trading-buddy-diego-9f3a7c`.
3. In the app: tap **+** → **"Subscribe to topic"** → paste the same string.
4. In `.env`, set:
   ```
   NTFY_TOPIC=trading-buddy-diego-9f3a7c
   ```
5. `make docker-down && make docker-up` to reload the backend.

### What you'll receive

Title: `↑ USTEC 15m @ 29654.30` (or `↓` for breakdowns)
Body: `Nivel rompido: 29635.24 | Expansao: 1.34x ATR | Strength: 74/100 | Bar: 18:35 UTC`
Tags: arrow + asset name (emoji rendering on iOS / Android)
Priority: 2-5 based on strength (5 = urgent on iOS, bypasses Do Not Disturb)

You also get a **Perfil do Dia** push (see above) when the day is unusually thin
or expansive: e.g. `⚠️ Dia FRACO · potencial 5/100` with the reasons in the body.
Sent at most once per day per regime — silent on ordinary (`NORMAL`) days.

### Dedup

The backend keeps a 24h record of pushed signal IDs in Redis. A
breakout that shows up in 10 consecutive ticks fires **one** push.
Container restarts do not re-spam (the record survives).

### Self-hosting

If you want full privacy (no third-party broker), spin up your own
ntfy server (`docker run binwiederhier/ntfy serve`) and set
`NTFY_SERVER=http://your-host:80`. ntfy is open-source and the
backend speaks to any compatible server.

## Autostart at macOS login

```bash
make autostart-install     # registers a launchd agent
make autostart-status      # check agent state + tail the log
make autostart-uninstall   # remove the agent
make autostart-run         # smoke-test the script without rebooting
```

What gets installed:
- `~/Library/LaunchAgents/com.trading-buddy.autostart.plist` — registered with `launchctl load -w`
- The plist runs `scripts/autostart-stack.sh` at login
- Logs: `~/Library/Logs/trading-buddy/autostart.log`

The script waits up to 3 minutes for the Docker daemon to become ready
(Docker Desktop usually takes a few seconds to launch after login), then
runs `make docker-up`. For this to work, also turn on **Docker Desktop →
Settings → "Start Docker Desktop when you log in"**, otherwise the agent
will time out waiting for Docker.

## Backend HTTP surface (for the frontend)

The backend runs FastAPI in the same process as the tick loop. Each new
`DashboardTick` is fanned out to connected WebSocket clients.

```
GET    /health                            liveness probe
GET    /api/tick                          latest DashboardTick (503 until first)
GET    /api/vix/history?lookback_days=N   5m VIX bars (1-60 day lookback)
POST   /api/brief                         on-demand macro briefing (or raw snapshot)
GET    /api/qa                            list saved Q&A entries (updated-first)
POST   /api/qa                            create a Q&A entry (201)
PUT    /api/qa/{id}                       update a Q&A entry (404 if missing)
DELETE /api/qa/{id}                       delete a Q&A entry (204 / 404)
WS     /ws/ticks                          streams each new tick
```

CORS is open for `http://localhost:3000` and `http://127.0.0.1:3000` by
default. For remote deploys, override the allowlist in
`backend/api/app.py:DEFAULT_CORS_ORIGINS`.

## Out of scope (phase 2+)

- Frontend (a `frontend/` placeholder is reserved).
- Telegram / push notifications.
- Real-time VIX put/call ratio and option skew (needs paid CBOE/ORATS data).
- Backtesting of the bias signal vs price.
- Auto-fire of LLM explainers around scheduled events.
- Multi-user / authentication.
