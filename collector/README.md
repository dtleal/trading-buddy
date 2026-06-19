# MT5 Order-Flow Collector (Windows)

Streams live **bid/ask · footprint · tape · pressure** from your MetaTrader 5
terminal to the trading-buddy backend, which renders it on the dashboard for
**USTEC, USA500 (→ SPX) and GOLD**. The dashboard's top-of-book panel is a
real-time bid/ask tick chart (the demo DOM book is mirrored, so the ladder was
dropped in favour of the genuinely-real top-of-book quote).

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
   MT5 attached: source=FTMO terminal=... connected=True account=...
   tape source: quote-tick flow ...        (only if synthesize_trades_from_quotes=true)
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

Most retail CFD feeds (incl. FTMO demo) do **not** send real order flow. Know
what you are looking at:

| Panel | Source | Trustworthy? |
|---|---|---|
| **Bid/Ask tick chart** | broker top-of-book quote | ✅ real (price movement) |
| **DOM depth (sizes)** | broker book | ⚠️ on demo accounts it is often **mirrored** (bid size = ask size at every level) → imbalance is always 0; we ingest the book only for the top-of-book quote, the ladder isn't shown |
| **Tape / Footprint / Pressure** | **derived** from quote-tick direction when there are no real trade ticks | ⚠️ direction is sound; **"volume" is a tick count, not contracts** |

With quote-tick synthesis the aggressor is inferred by the **tick rule** on the
mid price: an up-tick is a buy (at the ask), a down-tick is a sell (at the bid),
each counting as 1. That makes footprint **delta** and the **pressure bar** a
proxy for aggression, not exchange-grade volume.

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
| `synthesize_trades_from_quotes` | `true` for feeds with **no** times&trades: builds tape/footprint/pressure from quote-tick direction. `false` only if your broker sends real trade ticks. |
| `liquidity_baseline_days` | Sessions used for the **day-outlook liquidity gauge** baseline (default `20`). The collector compares today's cumulative tick volume to the median of the prior N sessions at the same time-of-day and pushes the ratio to the backend, which folds it into the "Perfil do Dia" banner/alert. `0` disables. |
| `liquidity_poll_seconds` | How often (s) to recompute + push that ratio (default `60`). It reads ~3 weeks of M5 bars, so it is throttled well below the tick poll. `0` disables. |
| `symbols[]` | Map each backend symbol to **your broker's exact MT5 name**. `backend` must be one of `USTEC` / `SPX` / `GOLD`. `mt5` is whatever your broker calls it (`US100.cash`, `Usa500`, `XAUUSD`, …). |
| `symbols[].footprint_tick` | Optional price step used to group footprint rows (e.g. `1.0` for an index ~28000, `0.1` for gold). Omit to auto-derive from the broker tick size. Keeps a continuous quote feed from fragmenting into thousands of cells. |
| `mt5.sources[]` | Priority list of terminals; each `{name, path}` is tried in order until one attaches. `path` is the `terminal64.exe`. Add `login`/`password`/`server` only to drive a specific account. |

> ⚠️ The backend tracks **SPX** (not "USA500"). Map your broker's S&P symbol to
> `"backend": "SPX"`. Same for gold → `"backend": "GOLD"`.

`config.json` holds your ingest token and is **git-ignored** — never commit it.
`config.example.json` is the committed template.

## Enable on the backend

In the backend `.env`:

```
ORDERFLOW_ENABLED=true
ORDERFLOW_INGEST_TOKEN=<long-random-string-same-as-collector-token>
# optional overrides:
# ORDERFLOW_SYMBOLS=USTEC,SPX,GOLD
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
| DOM fills but tape/footprint/pressure stay empty | Broker sends no real trade ticks | Set `synthesize_trades_from_quotes: true` |
| Flow appears then drops every ~50s | (already fixed) collector now answers backend keepalive pings | Pull latest `mt5_orderflow_collector.py` |
| Backend hangs / `/api/orderflow` times out under quote synthesis | (already fixed) per-trade snapshot + unbounded footprint cells | Pull latest backend; ensure `footprint_tick` is set per symbol |

Quick health check from the backend host:

```
curl -s http://localhost:8000/api/orderflow      # [] means nothing is feeding
```
