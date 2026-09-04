# MT5 Order-Flow Collector (Windows)

Streams live **bid/ask · footprint · tape · pressure · open positions** from your
MetaTrader 5 terminal to the trading-buddy backend, which renders it on the
dashboard for **USTEC, USA500 (→ SPX) and GOLD**. The dashboard's top-of-book
panel is a real-time bid/ask tick chart. With `synthesize_trades_from_quotes` on,
that bid/ask is taken from the **live quote tick** — not the broker's DOM book,
which on these CFD demo feeds is mirrored *and freezes* (it stopped updating
mid-day and left the chart stuck), so it is no longer trusted as the quote source.

It also mirrors your **open positions** live (entry, floating P&L, time-in-trade,
SL/TP) and the backend overlays deterministic **in-trade alerts** on them
(flow turning against the position; in-profit-but-momentum-stalling). The alerts
are decision support, not advice, and on synthesized-tape CFD feeds they are a
directional proxy (see the data-quality table below).

**Order execution is OFF by default.** Optionally the collector can *close*
positions — a whole-account profit-target **auto-close**, a per-asset
**"fechar tudo"** button, and a per-asset **"breakeven"** button (moves every
open position's stop-loss to its entry) in the UI. These are the only paths that
place/modify orders, and they require an explicit local opt-in
(`allow_auto_close: true` in `config.json`) **plus** arming/clicking in the UI.
See [Auto-close & manual close](#auto-close--manual-close).

This bridge **only reads market data** — it never places orders.

```
[ Your Windows PC ]                         [ Backend (Docker / WSL or KVM) ]
  MT5 terminal (logged in)                    tb-backend (FastAPI)
        │  MetaTrader5 lib                          │
  mt5_orderflow_collector.py  ──WS push──▶  /ws/ingest/orderflow
                                                    │ aggregates
                                             /ws/orderflow ──▶ dashboard panels
```

## Why it must run on Windows, with MT5 open

The `MetaTrader5` Python package is Windows-only and talks to the **running
terminal** over IPC — it cannot run inside the Docker/Linux backend. Keep both
the terminal (logged into your broker) **and** this script running while you
want live order flow. Close either → the flow panels go stale (the rest of the
dashboard keeps working).

---

## Quick start (local backend in Docker/WSL)

> This is the exact recipe that works against the local stack. Follow it in
> order; the [Troubleshooting](#troubleshooting) table maps every common failure
> back to a step here.

1. **Open MT5 and log in** to the broker you want to read. Confirm the
   bottom-right shows *connected* (a ping/load value, not "No connection").
   Use a terminal that actually publishes data — see
   [Pick the right terminal](#pick-the-right-terminal).

2. **Install the Python deps into the same Windows Python you will run.** The
   collector dies immediately at startup if `MetaTrader5` is missing.

   ```powershell
   python -m pip install -r requirements.txt
   python -c "import MetaTrader5, websocket; print('deps OK')"
   ```

3. **Make sure the backend is up** (Docker): `docker ps` should show
   `…-backend-1`. From the repo root: `make docker-up`.

4. **Create `config.json`** from the example and edit it (details
   [below](#configure-configjson)):

   ```powershell
   copy config.example.json config.json
   notepad config.json
   ```

   For the **local** backend, `backend_ws_url` **must** use `127.0.0.1`, not
   `localhost` (see the gotcha in Troubleshooting):

   ```
   ws://127.0.0.1:8000/ws/ingest/orderflow
   ```

5. **Run it** (and leave the window open):

   ```powershell
   python mt5_orderflow_collector.py --config config.json
   ```

   Or just double-click **`start_collector.bat`**.

6. **Verify.** The console should print, in order:

   ```
   MT5 attached: source=ActivTrades terminal=... connected=True account=950191
   tape source for UsaTecSep26: quote-tick synthesis (auto-detected)   ← one line per symbol; says "real times&trades" when the feed has a usable tape
   Connected to backend ingest: ws://127.0.0.1:8000/ws/ingest/orderflow
   ```

   Then `curl http://localhost:8000/api/orderflow` returns data (not `[]`), and
   the dashboard's pressure bar + flow panels go live within seconds.

---

## Keep it running automatically (watchdog)

The collector is a console process: if its window is closed, the PC reboots, or
it crashes, the flow goes stale until someone restarts it. To make it
self-healing, register the scheduled task **once** (elevation prompt):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File install_watchdog_task.ps1
```

What it sets up:

- **`watchdog.ps1`** runs every minute. If no `mt5_orderflow_collector` python
  process is alive, it relaunches one via `run_supervised.bat`. Idempotent — does
  nothing when the collector is already up.
- **`run_supervised.bat`** is the unattended launcher (no `pause`): when python
  exits, the window closes cleanly and the next watchdog tick brings it back.
- The task **`MT5OrderflowCollector`** fires the watchdog every minute in the
  interactive session, so after a reboot the collector is back within ~1 minute.

MT5 must still be open and logged in — if it isn't, the collector exits and the
watchdog keeps retrying until MT5 is available again. Manage the task with
`Get-ScheduledTask MT5OrderflowCollector`, test it on demand with
`Start-ScheduledTask MT5OrderflowCollector`, or remove it with
`Unregister-ScheduledTask MT5OrderflowCollector`.

> Running these scripts from a `\\wsl.localhost\...` path while elevated can fail
> (the UNC share isn't mounted in the elevated context). If that happens, copy
> the script to a local path like `C:\Users\<you>\` and run it from there.

---

## Access the dashboard from another device (same LAN)

The stack binds `0.0.0.0` (frontend `:3000`, backend `:8000`), and `~/.wslconfig`
uses `networkingMode=mirrored`, so WSL shares the Windows host's network
interfaces — no portproxy needed. Two things make it reachable from a phone or
laptop on the same network:

1. **Open the firewall** (host + the WSL Hyper-V firewall, which blocks inbound
   by default). Run once, elevated, from the repo root:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\open_lan_ports.ps1
   ```

   The rules are scoped to `RemoteAddress=LocalSubnet`, so the ports are reachable
   only from the local network, never the open internet.

2. **Browse to the host's LAN IP** from the other device, e.g.
   `http://192.168.15.5:3000` (use whichever host IP is on the device's network;
   `ipconfig` on Windows lists them). The device must be on the **same subnet**.

Verify the bind from inside WSL with `curl http://<lan-ip>:3000` (200 = good). A
`Test-NetConnection` from the Windows host to its *own* mirrored LAN IP returns
`False` even when it works — test from the actual external device instead.

For access from **outside** the LAN (internet), don't expose these ports — use a
tunnel (Tailscale, Cloudflare Tunnel) or a router port-forward.

---

## Pick the right terminal

Not every broker publishes the data the panels need. Before anything else, check
what your symbol actually provides:

- **DOM (book):** in MT5 right-click the symbol → **Depth of Market** (Alt+B). A
  ladder with sizes → the DOM panel will fill. Empty / price only → no depth.
- **Times & Trades (real volume):** if `copy_ticks_from(..., COPY_TICKS_TRADE)`
  returns nothing, the broker sends **no real traded volume** — common for CFD
  brokers. In that case enable quote-tick synthesis (next section) so the tape /
  footprint / pressure are derived from price movement instead.

If you run multiple terminals, point `mt5.sources[].path` at the specific
`terminal64.exe` so you attach to the one that has the data — attaching to the
wrong broker is the difference between a full flow and an empty dashboard.

---

## What is real vs derived (important)

Most retail CFD feeds (incl. ActivTrades) do **not** send real order flow. Know
what you are looking at:

| Panel | Source | Trustworthy? |
|---|---|---|
| **Bid/Ask tick chart** | **live quote tick** (`bid`/`ask`) under quote synthesis; raw DOM top-of-book otherwise | ✅ real (price movement) |
| **DOM depth (sizes)** | broker book | ⚠️ on demo accounts it is often **mirrored** (bid size = ask size at every level) → imbalance is always 0; worse, it can **freeze** for hours. Not used as the quote source when synthesis is on; the ladder isn't shown |
| **Tape / Footprint / Pressure** | **real times&trades** (flags + `volume_real`) when the feed exposes one (auto-detected); otherwise **derived** from quote ticks | ✅ real when the tape is real; ⚠️ on quote-only feeds direction is sound but **"volume" is a tick count, not contracts** (unless the tick carries a size) |
| **Open positions** | `mt5.positions_get()` (read-only) | ✅ real (your live entry, P&L, SL/TP, time-in-trade) |
| **M5 candles (Bandas tab)** | `copy_rates_from_pos` M5 (read-only), bar times converted to true UTC | ✅ real broker bars — the same candles your MT5 chart draws. The route drawn on top is measured from those same bars (what price did the last times it sat at this spot in the band), never a model's opinion |
| **Account balance/equity** | `account_info()` (balance/equity) + `history_deals_get` reconstruction (read-only) | ✅ real — feeds the "Saldo da conta" chart: a per-trade balance step curve (manual + bot, from the deal history) tipped with live equity, pushed on the `balance_history` + `account_pnl` messages (~30s) |
| **Closed-trade history (Performance tab)** | `history_deals_get` grouped by `position_id` (read-only) | ✅ real — every round-trip trade the account made, manual AND bot, with the broker's own profit/commission/swap. Pushed on the `trade_history` message every `history_poll_seconds` (default 300s). Bot trades carry the magic `770078` (older ones, the `trading-buddy …` comment) so manual and bot can be told apart |
| **Depósitos / saques (balance operations)** | `history_deals_get` over the account's whole life, non-trade deals | ✅ real — pushed with the trade history so the Performance tab can keep "money paid in" apart from "money made". Without it a $1,000 deposit reads as if the account had always held it |
| **In-trade alerts** | position + flow lean (`pressure_against`, `take_profit`) | ⚠️ deterministic, but only as sound as the synthesized flow it reads — decision support, not advice |
| **Auto-close / fechar tudo** | `mt5.order_send` (only if `allow_auto_close`) | ✅ real order execution — closes your positions for real |
| **Breakeven (SL → entry)** | `mt5.order_send` `TRADE_ACTION_SLTP` (only if `allow_auto_close`) | ✅ real order modification — moves your stops for real |
| **Chart marker** | `mt5.order_send` `TRADE_ACTION_PENDING` at min lot (only if `allow_auto_trade`) | ✅ real pending order — draws the entry line on the chart and **can fill** (0.01 lot) |

With quote-tick synthesis the aggressor is inferred per tick, strongest evidence
first (Lee-Ready adapted to the feed): broker BUY/SELL flags when present → a
nonzero `last` vs the quote (at/above the ask = buy, at/below the bid = sell) →
the **tick rule** on the mid price (up-tick = buy, down-tick = sell). Each print
is volume-weighted when the tick carries a size; when it doesn't, it counts as 1
— footprint **delta** and the **pressure bar** are then a tick-count proxy for
aggression, not exchange-grade volume. `python diag_forces.py` shows which case
your feed is, per symbol.

For exchange-grade footprint/delta you'd switch the backend to a real CME feed
(e.g. Databento) — this collector is the zero-cost MT5 path.

---

## Configure `config.json`

| Field | What |
|---|---|
| `backend_ws_url` | Backend ingest socket. **Local Docker/WSL:** `ws://127.0.0.1:8000/ws/ingest/orderflow` (use `127.0.0.1`, never `localhost`). **KVM:** `ws://72.62.15.111:8057/ws/ingest/orderflow`. |
| `token` | Must match `ORDERFLOW_INGEST_TOKEN` in the backend `.env`. |
| `poll_interval_ms` | How often to poll MT5 (250 ms is a good start). |
| `book_depth` | Max DOM rungs per side to send (10). |
| `synthesize_trades_from_quotes` | Tape source. **`null`/absent = auto-detect per symbol (recommended)**: uses the broker's real times&trades (aggressor flags + real volume) when `COPY_TICKS_TRADE` has usable prints, else synthesizes from quote ticks (`last` vs bid/ask, mid tick test; volume-weighted when the tick carries a size, else count=1/tick). `true` = force synthesis; `false` = force the real tape. Re-checked every 5 min while running. Run `python diag_forces.py` to see empirically what your feed exposes. |
| `liquidity_baseline_days` | Sessions used for the **day-outlook liquidity gauge** baseline (default `20`). The collector compares today's cumulative tick volume to the median of the prior N sessions at the same time-of-day and pushes the ratio to the backend, which folds it into the "Perfil do Dia" banner/alert. `0` disables. |
| `liquidity_poll_seconds` | How often (s) to recompute + push that ratio (default `60`). It reads ~3 weeks of M5 bars, so it is throttled well below the tick poll. `0` disables. |
| `candles_poll_seconds` | How often (s) to push the **M5 candles** that feed the frontend's Bandas tab (Bollinger + typical route ahead). Default `5`. `0` disables. |
| `candles_bars` | How many M5 bars to send per push (default `120`, newest last — the final bar is the one still forming). This is what the chart draws. |
| `candles_history_seconds` | How often (s) to send the **deep backfill** the band statistics read (default `600`). Also sent on every reconnect, so a restarted backend gets its history immediately. `0` disables the backfill. |
| `candles_history_bars` | How many M5 bars that backfill carries (default `1500`, ~5 days). The backend merges it with the live push by bar timestamp, so more history means a bigger sample for "what happened the last times price sat here". Must be greater than `candles_bars` to be sent at all. |
| `history_days` | How far back (days) to rebuild the **closed-trade history** the Performance tab reads (default `180`). The collector groups the broker's deals by position into round-trip trades and pushes them; the backend keeps everything it has ever received, so a shorter window only limits how far back a FRESH backend can be filled. `0` disables. |
| `history_poll_seconds` | How often (s) to re-read and push that history (default `300`). It walks months of deals, so keep it slow; it is also pushed on every reconnect. `0` disables. |
| `positions_poll_seconds` | How often (s) to read + push your **open positions** for the live P&L / time-in-trade panel and in-trade alerts (default `0.25`). Reading is always safe. `0` disables position reading entirely. |
| `allow_auto_close` | **Execution gate** (default `false` = strictly read-only). `true` lets this collector place **closing** orders when the backend profit target fires or you click "fechar tudo". Only enable on a machine/account where you accept automated execution — **test on DEMO first**. Never opens positions. |
| `allow_auto_trade` | **OPENING gate** for the explosion-scalper bot (default `false`). `true` lets the bot OPEN positions on bursts — but the collector **refuses to open unless the account is DEMO** (or `allow_live_auto_trade: true`, below), no matter this flag, and the bot also requires `allow_auto_close: true` (it must be able to close to exit/stop) or the backend won't arm it. Requires AutoTrading on in MT5. **Also gates the [chart marker](#chart-marker-mark-a-recommended-entry)** — a user-initiated min-lot pending order which, unlike the bot, is **not** demo-restricted. |
| `allow_live_auto_trade` | **LIVE override** for the scalper bot (default `false` = demo-only, safe). `true` lets the bot OPEN **real** positions on a **non-demo** account (e.g. the live ActivTrades account, which MT5 reports as REAL — not DEMO). Only meaningful with `allow_auto_trade: true`. **Danger:** real orders on a funded/challenge account can count against its rules. Size the lots down (per-asset, in the UI) — 0.01 is the broker minimum — before enabling. |
| `symbols[]` | Map each backend symbol to **your broker's exact MT5 name**. `backend` must be one of `USTEC` / `SPX` / `GOLD` / `US30` / `GER40` / `EURUSD`, and the list must cover every entry in the backend's `ORDERFLOW_SYMBOLS`. `mt5` is whatever your broker calls it — on ActivTrades: `UsaTecSep26`, `Usa500Sep26`, `GOLD`, `UsaIndSep26`, `Ger40Sep26`, `EURUSD`. |
| `symbols[].footprint_tick` | Optional price step used to group footprint rows (e.g. `1.0` for an index ~28000, `0.1` for gold, `0.0001` (one pip) for EURUSD). Omit to auto-derive from the broker tick size. Keeps a continuous quote feed from fragmenting into thousands of cells. |
| `mt5.sources[]` | Priority list of terminals; each `{name, path}` is tried in order until one attaches. `path` is the `terminal64.exe`. Add `login`/`password`/`server` only to drive a specific account. |

> ⚠️ The backend name is not always the broker name. It tracks **SPX** (the UI
> shows it as "USA500"), so map your broker's S&P symbol to `"backend": "SPX"`.
> Same idea for gold → `"backend": "GOLD"`. On ActivTrades the four index CFDs
> are **forward contracts**: the expiry is part of the name (`UsaTecSep26`) and
> it **rolls every quarter**, so when the contract expires you must edit
> `symbols[]` to the next one (`Dec26`) or the flow goes dead. `GOLD` and
> `EURUSD` are spot and never change.

`config.json` holds your ingest token and is **git-ignored** — never commit it.
`config.example.json` is the committed template.

## Auto-close & manual close

Two ways to close positions from the dashboard. **Both place real orders and are
off until you opt in.**

- **Whole-account auto-close** — when the *summed floating P&L of all open
  positions* reaches the target, the backend tells the collector to close
  everything. It **arms itself by default** at `ORDERFLOW_AUTOCLOSE_DEFAULT_USD`
  ($500) as soon as the collector connects with close capability, **re-arms after
  each fire**, and survives backend restarts / UI refreshes — so it's always on
  without clicking. A manual disarm in the UI turns the default-on off until you
  arm again; set the env to `0` to disable auto-arming entirely. Built for the
  "+$500 then it reverted before I could click" case.
- **Per-asset "fechar tudo"** — a button at the top of each symbol's card closes
  all positions for that symbol on demand (2-click confirm). Handy when you get
  the "em lucro mas momentum esfriou" alert and want out of just that asset.
- **Per-asset "breakeven"** — a button next to it moves every open position on
  that symbol to breakeven (SL → entry price, keeping the TP; 2-click confirm).
  The collector only moves positions already in profit — for one still underwater
  the SL would sit on the wrong side of the market and the broker would reject it,
  so those are skipped and reported (`skipped` in the result). Positions already
  at/beyond breakeven are left alone so a trailed stop is never loosened.
- **Per-asset P&L total** — each card's header shows the summed floating P&L of
  that symbol's open positions (green/red), so you read the number you're closing
  or protecting right above the two buttons. Shown read-only even when execution
  is off.

**Safety model (defense in depth):**

1. **Local opt-in** — nothing executes unless `allow_auto_close: true` in this
   `config.json`. With it `false` (default), the backend can fire all it wants
   and the collector refuses and reports back; the UI shows "execução
   desabilitada". The collector logs a loud warning on startup when it's `true`.
2. **UI action** — even enabled, it only fires when you ARM a target / click the
   button. DESARMAR is an always-available kill switch.
3. **One-shot** — auto-close disarms the instant it fires; it never loops.
4. **Close/protect-only** — it only ever *closes* existing positions or tightens
   their stop to breakeven, never opens. (Breakeven rides the same
   `allow_auto_close` gate — it's still an `order_send`.)
5. The brain (the target decision) lives in the backend and is unit-tested; the
   collector is a thin executor gated by step 1.

### Chart marker (mark a recommended entry)

When the analysis calls a level ("GOLD — vender no repique 4000–4004"), you can
drop a **min-lot (0.01) pending order** at that zone so the entry shows as a line
on the MT5 chart — the MetaTrader5 Python API can't draw chart objects, so a
resting order is the only way to mark a price from code.

```bash
# offset = price-points from the CURRENT market (the safe form — never mixes the
# yfinance level scale with the broker tape scale). Positive = above market.
curl -X POST http://localhost:8000/api/orderflow/mark/GOLD \
  -H 'Content-Type: application/json' -d '{"side":"sell","offset":5.7}'
# or an absolute price on the broker's feed:
curl -X POST http://localhost:8000/api/orderflow/mark/GOLD \
  -H 'Content-Type: application/json' -d '{"side":"buy","price":3985.0}'
```

- **Gated by `allow_auto_trade`** (it's an `order_send` that can fill), but —
  unlike the scalper bot — it is **user-initiated and NOT demo-restricted**, and
  defaults to `lots: 0.01`.
- The collector snaps the price to the symbol tick, clears the broker's minimum
  stop distance, and picks **LIMIT vs STOP automatically** by side + whether the
  target sits above/below the market, so the order is always accepted.
- **One marker per symbol**: each new marker first cancels the previous one, so
  the auto-placing analysis (`/5min-analysis` fires a marker on every
  comprar/vender verdict) never stacks 0.01 orders. Markers are matched by a
  **magic number** (`770077`), *not* the comment — the broker truncates order
  comments to ~16 chars, so only the magic reliably identifies our own markers;
  hand-placed orders (no magic) are never touched.
- It **can fill** at 0.01 — it's a real (negligible) order, not a pure annotation.
  A marker placed **at/near the current price is ephemeral** (price crosses it and
  it fills or is dropped in seconds); one at a genuine distance (a "repique"
  entry away from market) rests as a visible line. Cancel it in MT5, or it rides
  the per-asset close which also cancels pendings.

### Explosion-scalper bot (opens AND closes — demo only by default)

An optional deterministic bot that **opens** scalps on detected bursts and exits
the whole account at a profit target / loss stop. It is the highest-risk feature,
so it's gated hardest:

- **Opens** only when `allow_auto_trade: true` **and** `allow_auto_close: true`
  (it must be able to close to exit/stop) **and** the account is **DEMO** — or you
  set `allow_live_auto_trade: true` to accept **real** orders on a non-demo
  account (e.g. the live ActivTrades one). Then click **LIGAR** in the UI. **Lot
  size is configurable per asset in the UI** (button **Lotes** → set each, or
  "mín 0.01 em tudo"); defaults USTEC 0.1 / USA500 0.04 / US30 0.2 / GER40 0.04
  / gold 0.12 lt — the index CFDs are worth 5x-50x an FTMO `.cash` lot. Up to 6 positions per symbol; entries
  paced by a cooldown.
- **Entry = burst + grid (market-maker)**: a burst (short-window range expansion
  + strong directional pressure) opens **1 market order plus a grid of limit
  orders** spaced below (buy) / above (sell) by `0.5×` the recent per-bar range
  (ATR proxy) — so a pullback fills more at better prices instead of stacking at
  one price. **Thin sessions are skipped** (liquidity ratio < ~0.75). One
  direction per symbol — never the opposite side of an open position (no hedge).
- **Hybrid reverse**: the grid catches pullbacks, but if price **breaks past the
  whole region** (deepest level + buffer), the trade failed → it closes the
  symbol (the collector also **cancels the unfilled grid limits**) and can flip
  on the next burst. (Falls back to a lean-based reverse if no grid is recorded.)
- **Trailing profit lock**: tracks each symbol's peak unrealized P&L; once a
  meaningful gain (≥ $40) gives back 40% of its peak while still positive, it
  banks that symbol — so a winning move that reverses isn't given back to
  breakeven.
- **Exit** = whole-account close at **+profit_target** (banks the win, then
  **re-arms** to keep scalping — 24h mode) and a hard daily stop at **−loss_stop**
  on the *session* P&L (realized + floating), which closes all and stops for good.
  Defaults +$350 / −$900. **DESLIGAR** is the kill switch.
- It is a *mechanism*, not a proven edge — forward-test on demo. Note: the
  armed/session state lives in backend memory, so a backend restart disarms it
  (re-arm to resume).

**Trade history (for performance analysis):** every bot execution — opens (with
entry price, side, lots, ticket) and closes (reason: target / stop / reverse /
lock) — is written to the `bot_trades` table. Close **P&L is the broker's real
realized** (sum of the closing deals' profit + swap + commission, read via
`history_deals_get`), so the history matches MetaTrader — not a backend estimate.
**Only bot trades are recorded** (closes carry an `origin:"bot"` tag the collector
echoes back); the manual "fechar tudo" button and manual auto-close are excluded.
Read it back with `GET /api/orderflow/bot/trades?limit=N` (newest first). Recording
is best-effort — a DB problem is logged and never interrupts the bot. (The live
`realized`/UI number stays a fast floating estimate for the −loss_stop decision;
the persisted history is the faithful record.)

**You must enable AutoTrading in the MT5 terminal.** MT5 blocks all script/EA
orders until the **"AutoTrading" / "Algo Trading"** toolbar button is on (green;
shortcut **Ctrl+E**). Without it every close is rejected with `retcode=10027
"AutoTrading disabled by client"` and the position stays open — `allow_auto_close`
alone is not enough. Also check **Tools → Options → Expert Advisors → Allow
algorithmic trading**.

**Test on DEMO first.** On a funded/prop account this closes real money, and your
prop-firm rules on automation are your responsibility. Filling mode is broker
specific — the collector tries IOC → FOK → RETURN and reports any ticket it
couldn't close.

## Enable on the backend

In the backend `.env`:

```
ORDERFLOW_ENABLED=true
ORDERFLOW_INGEST_TOKEN=<long-random-string-same-as-collector-token>
# optional overrides:
# ORDERFLOW_SYMBOLS=USTEC,SPX,GOLD,US30,GER40,EURUSD
# ORDERFLOW_FOOTPRINT_INTERVAL_SECONDS=60
```

Local: restart the backend container. KVM: redeploy.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Console exits instantly, `ModuleNotFoundError: MetaTrader5` | Deps not installed in the Python you ran | `python -m pip install -r requirements.txt` into that exact interpreter (step 2) |
| `mt5.initialize() failed for every configured source` | MT5 closed, not logged in, or wrong `path` | Open MT5, log in, confirm "connected"; fix `mt5.sources[].path` |
| `Stream error: timed out` and no `Connected to backend ingest` line | `backend_ws_url` uses `localhost` → resolves to IPv6 `::1`, which does not reach the Docker port from Windows | Use `ws://127.0.0.1:8000/...` |
| Connects, but `/api/orderflow` is `[]` | Wrong broker symbols, or attached to a terminal with no data | Map `symbols[].mt5` to your broker's exact names; point `mt5.sources[].path` at the terminal that has the data |
| Backend up but `/api/orderflow` is `[]` after a restart, no collector in the backend logs | Collector window was closed when the stack restarted (MT5 still up, but no python process) | Relaunch `start_collector.bat`, or install the [watchdog](#keep-it-running-automatically-watchdog) so it comes back on its own |
| `Order-flow ingest refused` on the backend | `ORDERFLOW_ENABLED=false` or token mismatch | Set the env and make `token` match `ORDERFLOW_INGEST_TOKEN` |
| DOM fills but tape/footprint/pressure stay empty | Broker sends no real trade ticks AND the config forces the real tape (`false`) | Set `synthesize_trades_from_quotes` to `null` (auto-detect) or `true`; confirm what the feed exposes with `python diag_forces.py` |
| Flow appears then drops every ~50s | (already fixed) collector now answers backend keepalive pings | Pull latest `mt5_orderflow_collector.py` |
| Backend hangs / `/api/orderflow` times out under quote synthesis | (already fixed) per-trade snapshot + unbounded footprint cells | Pull latest backend; ensure `footprint_tick` is set per symbol |
| Bid/Ask chart stuck on "Coletando cotações…" while tape/pressure update | (already fixed) the broker's mirrored DOM **froze** and was the quote source, so the quote never changed | Pull latest `mt5_orderflow_collector.py` (quote synthesis now feeds the chart from the live quote tick). The chart also now shows "cotação parada" instead of failing silently |
| Auto-close / "fechar tudo" does nothing; `last_result` shows `retcode=10027 "AutoTrading disabled by client"` | The MT5 terminal's **AutoTrading** button is off — MT5 blocks all programmatic orders | Turn on **AutoTrading / Algo Trading** in the MT5 toolbar (green; **Ctrl+E**), and check Tools → Options → Expert Advisors → Allow algorithmic trading |

Quick health check from the backend host:

```
curl -s http://localhost:8000/api/orderflow      # [] means nothing is feeding
```
