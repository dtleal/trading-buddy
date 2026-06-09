# MT5 Order-Flow Collector (Windows)

Streams live **DOM / footprint / tape** from your MetaTrader 5 terminal to the
trading-buddy backend on the KVM, which renders it on the dashboard for
**USTEC, USA500 (→ SPX) and GOLD**.

This bridge **only reads market data** — it never places orders.

```
[ Your Windows PC ]                         [ KVM Linux ]
  MT5 terminal (logged in)                    tb-backend (FastAPI)
        │  MetaTrader5 lib                          │
  mt5_orderflow_collector.py  ──WS push──▶  /ws/ingest/orderflow
                                                    │ aggregates
                                             /ws/orderflow ──▶ dashboard panels
```

## Why it must run on Windows, with MT5 open

The `MetaTrader5` Python package is Windows-only and talks to the **running
terminal** over IPC. Keep both the terminal (logged into your broker) and this
script running while you want live order flow. Close either → the flow panels
go stale (the rest of the dashboard keeps working).

## One-time check: does your broker publish DOM?

1. In MT5, right-click the symbol (e.g. `USTEC`) → **Depth of Market**
   (shortcut **Alt+B**).
2. A ladder with **bid/ask sizes** → ✅ your broker publishes depth; the DOM
   panel will fill.
3. Empty / price only → ❌ no depth from this broker. Footprint + tape can
   still work *if* the broker sends trade ticks (see caveats below).

## Setup

Requires Python 3.10+ on Windows.

```powershell
cd collector
pip install -r requirements.txt
copy config.example.json config.json
notepad config.json          # edit token + symbol mapping (see below)
python mt5_orderflow_collector.py --config config.json
```

## Configure `config.json`

| Field | What |
|---|---|
| `backend_ws_url` | KVM backend ingest socket. Default port is **8057**: `ws://72.62.15.111:8057/ws/ingest/orderflow` |
| `token` | Must match `ORDERFLOW_INGEST_TOKEN` in the backend `.env` (see below). |
| `poll_interval_ms` | How often to poll MT5 (250 ms is a good start). |
| `book_depth` | Max DOM rungs per side to send (10). |
| `symbols[]` | Map each backend symbol to **your broker's exact MT5 name**. `backend` must be one of `USTEC` / `SPX` / `GOLD`. `mt5` is whatever your broker calls it (`USA500`, `US500`, `XAUUSD`, `GOLD`, …). |
| `mt5.*` | Leave `null` to attach to the already-running, logged-in terminal. Set `login`/`password`/`server` only to drive a specific account, or `path` to launch a specific terminal exe. |

> ⚠️ The backend tracks **SPX** (not "USA500"). Map your broker's S&P symbol to
> `"backend": "SPX"`. Same idea if your gold symbol is `XAUUSD`: map it to
> `"backend": "GOLD"`.

## Enable on the backend (KVM)

In `/root/trading-buddy/.env`:

```
ORDERFLOW_ENABLED=true
ORDERFLOW_INGEST_TOKEN=<long-random-string-same-as-collector-token>
# optional overrides:
# ORDERFLOW_SYMBOLS=USTEC,SPX,GOLD
# ORDERFLOW_FOOTPRINT_INTERVAL_SECONDS=60
```

Then redeploy the backend (`/update-kvm-trading-buddy-prod`). The collector
connects from your PC; the dashboard's **Fluxo (DOM · Footprint · Tape)**
section lights up.

## CFD data-quality caveats

- **DOM** depends entirely on your broker. No depth published → empty ladder.
- **Volume** on CFDs is *tick volume* (number of ticks), not real contracts.
- **Aggressor side** uses MT5 trade flags when present, else infers from
  last-vs-bid/ask. So footprint **delta is a proxy**, not exchange-grade.
- If `copy_ticks_from(..., COPY_TICKS_TRADE)` returns nothing, your broker
  isn't sending trade ticks → footprint/tape stay empty (DOM may still work).

For exchange-grade footprint/delta you'd switch the backend to a real CME feed
(e.g. Databento) — this collector is the zero-cost MT5 path.
