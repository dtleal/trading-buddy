"""MT5 → trading-buddy order-flow collector (Windows only).

Runs next to a logged-in MetaTrader 5 terminal, reads the broker's
depth-of-market and trade ticks for the configured symbols, and streams them
to the trading-buddy backend ingest WebSocket. The backend aggregates the raw
stream into DOM / footprint / tape views and fans them out to the dashboard.

WHY WINDOWS: the `MetaTrader5` Python package only works on Windows and only
while the MT5 *terminal* is running and logged into your broker. This script
is a thin bridge — it does not place orders, it only reads market data.

USAGE (PowerShell / cmd):
    pip install -r requirements.txt
    copy config.example.json config.json   # then edit config.json
    python mt5_orderflow_collector.py --config config.json

Keep this script AND the MT5 terminal running while you want live order flow
on the dashboard. Close either and the flow panels simply go stale.

CFD CAVEATS:
- DOM (`market_book_get`) only returns rungs if your broker publishes depth
  for that symbol. Many CFD brokers don't — check with Alt+B in MT5 first.
- "Volume" on CFDs is *tick volume* (count of price changes), not real traded
  contracts, and aggressor side is inferred. Treat footprint/delta as a proxy.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any

try:
    import MetaTrader5 as mt5  # type: ignore
except ImportError:  # pragma: no cover - only importable on Windows w/ MT5
    mt5 = None  # resolved at runtime; main() errors clearly if still None

try:
    from websocket import create_connection  # websocket-client
except ImportError:  # pragma: no cover
    create_connection = None  # type: ignore

logger = logging.getLogger("mt5_collector")

# MT5 DOM entry types (ENUM_BOOK_TYPE).
_BOOK_TYPE_SELL = 1  # ask side
_BOOK_TYPE_SELL_MARKET = 3
_BOOK_TYPE_BUY = 2  # bid side
_BOOK_TYPE_BUY_MARKET = 4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.setdefault("poll_interval_ms", 250)
    cfg.setdefault("book_depth", 10)
    if not cfg.get("backend_ws_url"):
        raise SystemExit("config: 'backend_ws_url' is required")
    if not cfg.get("symbols"):
        raise SystemExit("config: 'symbols' must list at least one mapping")
    return cfg


# --- MT5 session -------------------------------------------------------------


def _init_mt5(cfg: dict[str, Any]) -> str:
    """Attach to the first MT5 terminal in the configured priority list.

    Supports two config shapes:

      "mt5": { "sources": [
          {"name": "FTMO",        "path": "...\\FTMO MetaTrader 5\\terminal64.exe"},
          {"name": "ActivTrades", "path": "...\\ActivTrades MT5\\terminal64.exe"}
      ]}

      "mt5": { "path": "...", "login": ..., "password": "...", "server": "..." }

    The list form is the new preferred shape: each entry is tried in order until
    one succeeds (terminal must be open and logged in). Returns the resolved
    source name so the backend / UI can show which broker is feeding flow.
    """
    if mt5 is None:
        raise SystemExit(
            "MetaTrader5 package not importable. This collector only runs on "
            "Windows with the MT5 terminal installed. `pip install MetaTrader5`."
        )
    mt5_cfg = cfg.get("mt5") or {}
    sources = mt5_cfg.get("sources")
    if not sources:
        # Back-compat: treat single-source config as a length-1 list.
        sources = [
            {
                "name": mt5_cfg.get("name") or "MT5",
                "path": mt5_cfg.get("path"),
                "login": mt5_cfg.get("login"),
                "password": mt5_cfg.get("password"),
                "server": mt5_cfg.get("server"),
            }
        ]

    errors: list[str] = []
    for src in sources:
        name = src.get("name") or "MT5"
        kwargs: dict[str, Any] = {}
        if src.get("path"):
            kwargs["path"] = src["path"]
        if src.get("login"):
            kwargs.update(
                login=int(src["login"]),
                password=src.get("password", ""),
                server=src.get("server", ""),
            )
        if mt5.initialize(**kwargs):
            term = mt5.terminal_info()
            acct = mt5.account_info()
            logger.info(
                "MT5 attached: source=%s terminal=%s connected=%s account=%s",
                name,
                getattr(term, "name", "?"),
                getattr(term, "connected", "?"),
                getattr(acct, "login", "?"),
            )
            return name
        errors.append(f"{name}: {mt5.last_error()}")
        # Clean shutdown before trying the next candidate so init state is fresh.
        try:
            mt5.shutdown()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass

    raise SystemExit(
        "mt5.initialize() failed for every configured source:\n  - "
        + "\n  - ".join(errors)
    )


def _subscribe_symbols(symbols: list[dict[str, str]]) -> None:
    for m in symbols:
        broker = m["mt5"]
        if not mt5.symbol_select(broker, True):
            logger.warning("symbol_select(%s) failed: %s", broker, mt5.last_error())
        if mt5.market_book_add(broker):
            logger.info("DOM subscribed: %s → %s", broker, m["backend"])
        else:
            logger.warning(
                "market_book_add(%s) failed — your broker may not publish depth "
                "for this symbol (footprint/tape will still work). err=%s",
                broker,
                mt5.last_error(),
            )


# --- reads -------------------------------------------------------------------


def _read_book(backend: str, broker: str, depth: int) -> dict[str, Any] | None:
    items = mt5.market_book_get(broker)
    if not items:
        return None
    bids: list[list[float]] = []
    asks: list[list[float]] = []
    for it in items:
        price = float(it.price)
        volume = float(getattr(it, "volume_real", 0.0) or it.volume)
        if it.type in (_BOOK_TYPE_BUY, _BOOK_TYPE_BUY_MARKET):
            bids.append([price, volume])
        elif it.type in (_BOOK_TYPE_SELL, _BOOK_TYPE_SELL_MARKET):
            asks.append([price, volume])
    if not bids and not asks:
        return None
    bids.sort(key=lambda x: x[0], reverse=True)  # best (highest) first
    asks.sort(key=lambda x: x[0])  # best (lowest) first
    return {
        "type": "book",
        "symbol": backend,
        "asof": _now_iso(),
        "bids": bids[:depth],
        "asks": asks[:depth],
    }


def _tick_side(flags: int, last: float, bid: float, ask: float) -> str:
    """Aggressor side for a trade tick. Prefer broker flags; else infer."""
    if flags & mt5.TICK_FLAG_BUY:
        return "buy"
    if flags & mt5.TICK_FLAG_SELL:
        return "sell"
    if ask and last >= ask:
        return "buy"
    if bid and last <= bid:
        return "sell"
    return "unknown"


def _read_trades(
    backend: str, broker: str, since_msc: int
) -> tuple[list[dict[str, Any]], int]:
    """Return (trade messages newer than since_msc, new high-water time_msc)."""
    from_dt = datetime.fromtimestamp(max(since_msc, 0) / 1000.0, tz=timezone.utc)
    ticks = mt5.copy_ticks_from(broker, from_dt, 100000, mt5.COPY_TICKS_TRADE)
    if ticks is None or len(ticks) == 0:
        return [], since_msc
    out: list[dict[str, Any]] = []
    high = since_msc
    for t in ticks:
        tmsc = int(t["time_msc"])
        if tmsc <= since_msc:
            continue
        high = max(high, tmsc)
        last = float(t["last"]) or float(t["bid"] or t["ask"] or 0.0)
        if last == 0.0:
            continue
        vol = float(t["volume_real"]) if t["volume_real"] else float(t["volume"])
        side = _tick_side(int(t["flags"]), last, float(t["bid"]), float(t["ask"]))
        out.append(
            {
                "at": datetime.fromtimestamp(tmsc / 1000.0, tz=timezone.utc).isoformat(),
                "price": last,
                "volume": vol,
                "side": side,
            }
        )
    return out, high


# --- main loop ---------------------------------------------------------------


def _connect_backend(url: str, token: str):
    full = f"{url}?token={token}" if "token=" not in url else url
    ws = create_connection(full, timeout=10)
    logger.info("Connected to backend ingest: %s", url)
    return ws


def run(cfg: dict[str, Any]) -> None:
    if create_connection is None:
        raise SystemExit("websocket-client not installed. `pip install websocket-client`.")
    source_name = _init_mt5(cfg)
    _subscribe_symbols(cfg["symbols"])

    url = cfg["backend_ws_url"]
    token = str(cfg.get("token", ""))
    poll_s = max(cfg["poll_interval_ms"], 50) / 1000.0
    depth = int(cfg["book_depth"])
    # Start the tape from "now" — otherwise copy_ticks_from(0) reaches back to
    # 1970 and replays ancient history on the first poll. We only want trades
    # that print after the collector starts.
    start_msc = int(time.time() * 1000)
    since: dict[str, int] = {m["mt5"]: start_msc for m in cfg["symbols"]}
    last_book: dict[str, str] = {}  # broker -> last sent book payload (dedup)

    ws = None
    while True:
        try:
            if ws is None:
                ws = _connect_backend(url, token)
                # Identify which broker is feeding this stream — the backend
                # stamps every subsequent snapshot with this name so the UI can
                # label each column. Re-sent on every reconnect.
                ws.send(json.dumps({"type": "hello", "source": source_name}))
            for m in cfg["symbols"]:
                backend, broker = m["backend"], m["mt5"]
                book = _read_book(backend, broker, depth)
                if book:
                    # Skip unchanged books so we don't flood the backend with a
                    # full snapshot broadcast every poll when nothing moved.
                    sig = json.dumps([book["bids"], book["asks"]])
                    if sig != last_book.get(broker):
                        last_book[broker] = sig
                        ws.send(json.dumps(book))
                trades, since[broker] = _read_trades(backend, broker, since[broker])
                if trades:
                    ws.send(json.dumps({"type": "trades", "symbol": backend, "trades": trades}))
            time.sleep(poll_s)
        except KeyboardInterrupt:
            logger.info("Stopping (Ctrl-C).")
            break
        except Exception as exc:  # reconnect on any backend/socket hiccup
            logger.warning("Stream error: %s — reconnecting in 2s", exc)
            try:
                if ws is not None:
                    ws.close()
            except Exception:
                pass
            ws = None
            time.sleep(2.0)

    if ws is not None:
        try:
            ws.close()
        except Exception:
            pass
    if mt5 is not None:
        mt5.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="MT5 → trading-buddy order-flow collector")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    run(_load_config(args.config))


if __name__ == "__main__":
    main()
