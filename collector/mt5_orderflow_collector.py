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
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import MetaTrader5 as mt5  # type: ignore
except ImportError:  # pragma: no cover - only importable on Windows w/ MT5
    mt5 = None  # resolved at runtime; main() errors clearly if still None

try:
    import websocket  # websocket-client
    from websocket import create_connection
except ImportError:  # pragma: no cover
    websocket = None  # type: ignore
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
    # Day-outlook liquidity gauge: how many prior sessions feed the baseline,
    # and how often (seconds) we recompute + push the reading. 0 disables it.
    cfg.setdefault("liquidity_baseline_days", 20)
    cfg.setdefault("liquidity_poll_seconds", 60)
    # Open-position polling cadence (seconds). Positions carry live P&L, so we
    # refresh fast but throttle below the tick poll to avoid flooding. 0 disables
    # reading positions entirely.
    cfg.setdefault("positions_poll_seconds", 0.25)
    # Auto-close EXECUTION gate. False = strictly read-only (default): even if the
    # backend fires the profit target, the collector refuses to send orders. Must
    # be set true ON THIS MACHINE to allow closing positions automatically.
    cfg.setdefault("allow_auto_close", False)
    # Auto-TRADE gate (the explosion-scalper bot OPENING positions). Strictly
    # separate from allow_auto_close because opening is far riskier than closing.
    # Even when true, the collector refuses to open unless the account is a DEMO.
    cfg.setdefault("allow_auto_trade", False)
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


def _broker_tick(broker: str) -> float | None:
    """Best-effort tick size for a symbol, used to group footprint rows when the
    config doesn't pin one. Falls back to None (no grouping) if unavailable."""
    try:
        info = mt5.symbol_info(broker)
    except Exception:  # pragma: no cover - defensive
        return None
    if info is None:
        return None
    size = float(getattr(info, "trade_tick_size", 0.0) or 0.0)
    if size > 0:
        return size
    point = float(getattr(info, "point", 0.0) or 0.0)
    return point or None


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


def _read_positions(
    broker_to_backend: dict[str, str],
) -> dict[str, list[dict[str, Any]]] | None:
    """Read open positions live from MT5, grouped by backend symbol.

    READ-ONLY: `positions_get()` only queries; the collector never sends orders.
    Returns a dict with an entry for every configured backend symbol (empty list
    when flat, so the backend can clear a closed trade), or None on an MT5 error
    (so the caller leaves the last known state untouched rather than wiping it).

    `seconds_open` (time-in-trade) is computed here, not on the frontend: MT5's
    `position.time` is in the broker's *server* clock, so we subtract it from the
    same clock — the symbol's latest tick time — to avoid timezone skew. The UI
    then ticks the value up locally from when it arrives.
    """
    raw = mt5.positions_get()
    if raw is None:
        return None
    out: dict[str, list[dict[str, Any]]] = {b: [] for b in broker_to_backend.values()}
    for p in raw:
        backend = broker_to_backend.get(p.symbol)
        if backend is None:
            continue  # a position on a symbol we don't track
        tick = mt5.symbol_info_tick(p.symbol)
        broker_now = float(getattr(tick, "time", 0.0) or 0.0)
        seconds_open = max(0.0, broker_now - float(p.time)) if broker_now else 0.0
        side = "buy" if p.type == mt5.POSITION_TYPE_BUY else "sell"
        out[backend].append(
            {
                "ticket": int(p.ticket),
                "side": side,
                "volume": float(p.volume),
                "price_open": float(p.price_open),
                "price_current": float(p.price_current),
                "profit": float(p.profit),
                "sl": float(p.sl),
                "tp": float(p.tp),
                "seconds_open": seconds_open,
            }
        )
    return out


def _close_position(p) -> Any:
    """Send a market order that closes one open position. Returns the MT5
    order_send result (or None). Tries the common filling modes in turn because
    the accepted one is broker-specific (CFD brokers often reject the default)."""
    tick = mt5.symbol_info_tick(p.symbol)
    if p.type == mt5.POSITION_TYPE_BUY:
        order_type, price = mt5.ORDER_TYPE_SELL, float(getattr(tick, "bid", 0.0) or 0.0)
    else:
        order_type, price = mt5.ORDER_TYPE_BUY, float(getattr(tick, "ask", 0.0) or 0.0)
    base = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": p.symbol,
        "volume": float(p.volume),
        "type": order_type,
        "position": int(p.ticket),
        "price": price,
        "deviation": 50,
        "comment": "trading-buddy autoclose",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    result = None
    for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        result = mt5.order_send({**base, "type_filling": filling})
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            return result
        # Only a bad filling mode is worth retrying; any other failure is final.
        if result is not None and result.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
            return result
    return result


def _account_is_demo() -> bool:
    """True only when attached to a DEMO account. The auto-trade bot refuses to
    OPEN positions on anything else, no matter the config."""
    try:
        acct = mt5.account_info()
    except Exception:  # pragma: no cover - defensive
        return False
    return acct is not None and acct.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO


def _open_position(broker: str, side: str, lots: float) -> Any:
    """Open a market position (the scalper bot). Tries broker-specific filling
    modes in turn. Returns the MT5 order_send result (or None)."""
    tick = mt5.symbol_info_tick(broker)
    if side == "buy":
        order_type, price = mt5.ORDER_TYPE_BUY, float(getattr(tick, "ask", 0.0) or 0.0)
    else:
        order_type, price = mt5.ORDER_TYPE_SELL, float(getattr(tick, "bid", 0.0) or 0.0)
    base = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": broker,
        "volume": float(lots),
        "type": order_type,
        "price": price,
        "deviation": 50,
        "comment": "trading-buddy scalper",
        "type_time": mt5.ORDER_TIME_GTC,
    }
    result = None
    for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        result = mt5.order_send({**base, "type_filling": filling})
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            return result
        if result is not None and result.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
            return result
    return result


def _close_all_positions(broker_symbols: set[str] | None = None) -> dict[str, Any]:
    """Close open positions (fresh read). With `broker_symbols`, only those MT5
    symbols are closed (the per-asset button); None closes everything (the
    profit-target auto-close). Returns a result summary the backend records and
    shows in the UI. Best-effort: keeps going past a failure and reports which
    tickets could not be closed."""
    raw = mt5.positions_get()
    if raw is None:
        return {"ok": False, "closed": 0, "error": "positions_get() retornou None"}
    closed = 0
    errors: list[str] = []
    for p in raw:
        if broker_symbols is not None and p.symbol not in broker_symbols:
            continue
        result = _close_position(p)
        if result is not None and getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            closed += 1
            logger.info("Auto-close: closed %s #%s", p.symbol, p.ticket)
        else:
            rc = getattr(result, "retcode", "?")
            cm = getattr(result, "comment", "")
            errors.append(f"{p.symbol}#{p.ticket}: retcode={rc} {cm}")
            logger.warning("Auto-close FAILED for %s #%s: retcode=%s %s", p.symbol, p.ticket, rc, cm)
    return {"ok": not errors, "closed": closed, "errors": errors}


def _median(values: list[float]) -> float | None:
    """Median of a non-empty list, else None."""
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def _read_session_liquidity(
    backend: str, broker: str, baseline_days: int
) -> dict[str, Any] | None:
    """Compare today's session activity to the same-time-of-day baseline.

    Pulls M5 candles covering the last `baseline_days`+ sessions via
    `copy_rates_range`, buckets them by calendar date, and for each date measures
    activity up to the *same point in the session* as today's latest bar:

      - **volume**: cumulative tick volume (participation).
      - **range** : session travel so far (max high − min low) — this is the
        "candles minúsculos, preço não anda" signal; it reads tiny when the
        market is locked up even if a few ticks still print.

    Each is divided by the median of the prior sessions' same-cutoff value, so a
    ratio < 1 means today is thinner / quieter than usual. Both come from the MT5
    candles the collector already fetches — no yfinance, works on holidays when
    the cash index is closed but the CFD still prints.

    NOTE ON TIMEZONES: MT5 returns bar times in the broker's *server* clock, not
    UTC. We never convert — the date/minute-of-day bucketing is internally
    consistent across today and the baseline days, which is all the ratio needs.
    Returns None when there isn't enough history yet.
    """
    if mt5 is None:
        return None
    # ~ (baseline_days + 4) calendar days back to absorb weekends/holidays and
    # still land `baseline_days` sessions with data.
    span = timedelta(days=baseline_days + 4)
    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - span
    rates = mt5.copy_rates_range(broker, mt5.TIMEFRAME_M5, from_dt, to_dt)
    if rates is None or len(rates) == 0:
        return None

    # Bucket bars by (server-clock) date. Each entry: (minute_of_day, vol, high, low).
    by_date: dict[Any, list[tuple[int, float, float, float]]] = {}
    for r in rates:
        bar_dt = datetime.fromtimestamp(int(r["time"]), tz=timezone.utc)
        minute_of_day = bar_dt.hour * 60 + bar_dt.minute
        by_date.setdefault(bar_dt.date(), []).append(
            (minute_of_day, float(r["tick_volume"]), float(r["high"]), float(r["low"]))
        )
    if len(by_date) < 2:
        return None

    dates = sorted(by_date.keys())
    today = dates[-1]
    # Cut every day off at the same point as today's most-recent bar.
    cutoff = max(m for m, _, _, _ in by_date[today])

    def _vol(day: Any) -> float:
        return sum(v for m, v, _, _ in by_date[day] if m <= cutoff)

    def _range(day: Any) -> float:
        bars = [(hi, lo) for m, _, hi, lo in by_date[day] if m <= cutoff]
        if not bars:
            return 0.0
        return max(hi for hi, _ in bars) - min(lo for _, lo in bars)

    realized_vol = _vol(today)
    realized_range = _range(today)
    prior_days = dates[:-1][-baseline_days:]
    vol_samples = [v for v in (_vol(d) for d in prior_days) if v > 0]
    range_samples = [r for r in (_range(d) for d in prior_days) if r > 0]
    base_vol = _median(vol_samples)
    base_range = _median(range_samples)
    # Volume baseline is mandatory (it's the primary signal); range is a bonus.
    if not base_vol:
        return None

    msg: dict[str, Any] = {
        "type": "liquidity",
        "symbol": backend,
        "asof": _now_iso(),
        "realized_volume": realized_vol,
        "baseline_volume": base_vol,
        "ratio": realized_vol / base_vol,
        "sample_days": len(vol_samples),  # days that actually fed the baseline
    }
    if base_range:
        msg["realized_range"] = realized_range
        msg["baseline_range"] = base_range
        msg["range_ratio"] = realized_range / base_range
    return msg


def _quantize(price: float, tick: float | None) -> float:
    """Snap a price to the footprint row grid so a continuous quote feed doesn't
    fragment into thousands of distinct footprint cells. No tick → unchanged."""
    if not tick or tick <= 0:
        return price
    return round(round(price / tick) * tick, 10)


def _read_quote_flow(
    backend: str, broker: str, since_msc: int, last_mid: float | None, tick: float | None
) -> tuple[list[dict[str, Any]], int, float | None, tuple[float, float] | None]:
    """Synthesize a buy/sell tape from quote ticks when the broker has no
    times&trades (the common CFD case: COPY_TICKS_TRADE is empty).

    Aggressor is inferred by the tick rule on the mid price: an uptick means
    buyers are lifting the offer (side=buy at the ask), a downtick means sellers
    are hitting the bid (side=sell at the bid). Volume is unknown on these feeds,
    so each directional tick counts as 1 — the *count* of up vs down ticks is the
    pressure signal (delta), not a traded contract count. Returns
    (trades, new high-water time_msc, new last_mid, latest (bid, ask)).

    The latest (bid, ask) is the live top of book — on CFD feeds the broker's DOM
    (`market_book_get`) is a frozen, mirrored demo book, so the quote tick is the
    only genuinely live bid/ask. It feeds the bid/ask chart. None if no new tick.
    """
    from_dt = datetime.fromtimestamp(max(since_msc, 0) / 1000.0, tz=timezone.utc)
    ticks = mt5.copy_ticks_from(broker, from_dt, 100000, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return [], since_msc, last_mid, None
    out: list[dict[str, Any]] = []
    high = since_msc
    prev = last_mid
    last_quote: tuple[float, float] | None = None
    for t in ticks:
        tmsc = int(t["time_msc"])
        if tmsc <= since_msc:
            continue
        high = max(high, tmsc)
        bid = float(t["bid"])
        ask = float(t["ask"])
        if bid <= 0.0 or ask <= 0.0:
            continue
        last_quote = (bid, ask)  # freshest top of book, regardless of mid move
        mid = (bid + ask) / 2.0
        if prev is not None and mid != prev:
            if mid > prev:
                side, price = "buy", _quantize(ask, tick)
            else:
                side, price = "sell", _quantize(bid, tick)
            out.append(
                {
                    "at": datetime.fromtimestamp(tmsc / 1000.0, tz=timezone.utc).isoformat(),
                    "price": price,
                    "volume": 1.0,
                    "side": side,
                }
            )
        prev = mid
    return out, high, prev, last_quote


# --- main loop ---------------------------------------------------------------


def _connect_backend(url: str, token: str):
    full = f"{url}?token={token}" if "token=" not in url else url
    ws = create_connection(full, timeout=10)
    # Short read timeout so the poll loop can drain server keepalive pings
    # without blocking; sends of our tiny JSON frames still complete instantly.
    ws.settimeout(0.2)
    logger.info("Connected to backend ingest: %s", url)
    return ws


def _drain_control(
    ws,
    broker_to_backend: dict[str, str],
    allow_auto_close: bool,
    allow_auto_trade: bool,
    is_demo: bool,
) -> None:
    """Answer the backend's keepalive pings AND handle control commands.

    The collector is mostly send-only, but websocket-client only emits the
    protocol PONG for a server PING while inside recv(). Without this periodic
    drain the backend sees an unresponsive peer and drops the ingest socket as
    idle every ~30-50s (WinError 10053), causing visible gaps in the dashboard.
    A timeout here just means "no frame waiting".

    Commands the backend sends down this socket:
      - `close_all` / `close_symbol` — gated by `allow_auto_close`.
      - `open` (the scalper bot) — gated by `allow_auto_trade` AND a DEMO account.
    On refusal we report back so the UI never shows a phantom action. Any
    non-timeout socket error propagates so the outer loop reconnects.
    """
    try:
        raw = ws.recv()
    except websocket.WebSocketTimeoutException:
        return
    if not raw:
        return
    try:
        cmd = json.loads(raw)
    except (ValueError, TypeError):
        return
    if not isinstance(cmd, dict):
        return
    ctype = cmd.get("type")

    if ctype == "open":
        backend_sym = cmd.get("symbol")
        side = cmd.get("side")
        lots = float(cmd.get("lots", 0.0) or 0.0)
        brokers = [b for b, be in broker_to_backend.items() if be == backend_sym]
        if not brokers or side not in ("buy", "sell") or lots <= 0:
            ws.send(json.dumps({"type": "open_result", "ok": False,
                                "error": f"comando open inválido: {cmd}"}))
            return
        if not (allow_auto_trade and is_demo):
            reason = "allow_auto_trade=false" if not allow_auto_trade else "conta não é demo"
            logger.warning("Refusing open: %s", reason)
            ws.send(json.dumps({"type": "open_result", "ok": False, "symbol": backend_sym,
                                "error": reason}))
            return
        result = _open_position(brokers[0], side, lots)
        ok = result is not None and getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE
        logger.info("Bot open %s %s %s → ok=%s", side, brokers[0], lots, ok)
        # Fill price for the trade-history record: prefer the executed deal price.
        fill_price = float(getattr(result, "price", 0.0) or 0.0) if ok else None
        ws.send(json.dumps({"type": "open_result", "ok": ok, "symbol": backend_sym, "side": side,
                            "lots": float(lots),
                            "price": fill_price,
                            "ticket": getattr(result, "order", None) if ok else None,
                            "error": None if ok else f"retcode={getattr(result,'retcode','?')} "
                                                     f"{getattr(result,'comment','')}"}))
        return

    if ctype not in ("close_all", "close_symbol"):
        return

    # Resolve which broker symbols to close. close_all → everything (None).
    # close_symbol → the broker symbols mapping to the requested backend symbol.
    target_brokers: set[str] | None
    if ctype == "close_symbol":
        backend_sym = cmd.get("symbol")
        target_brokers = {b for b, be in broker_to_backend.items() if be == backend_sym}
        if not target_brokers:
            ws.send(json.dumps({"type": "autoclose_result", "ok": False, "closed": 0,
                                "error": f"símbolo desconhecido: {backend_sym}"}))
            return
    else:
        target_brokers = None

    logger.info("Received %s from backend: %s", ctype, cmd.get("reason", cmd.get("symbol", "")))
    if not allow_auto_close:
        logger.warning("Refusing %s: allow_auto_close is false on this collector", ctype)
        ws.send(json.dumps({"type": "autoclose_result", "ok": False, "closed": 0,
                            "error": "allow_auto_close=false no collector"}))
        return
    result = _close_all_positions(target_brokers)
    ws.send(json.dumps({"type": "autoclose_result", **result}))


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
    # When the broker publishes no times&trades, build the tape from quote-tick
    # direction instead (see _read_quote_flow). `mid` holds the last mid price
    # per symbol so we can classify the next tick as an up/down move.
    quote_mode = bool(cfg.get("synthesize_trades_from_quotes", False))
    mid: dict[str, float | None] = {m["mt5"]: None for m in cfg["symbols"]}
    # Liquidity gauge cadence (see _read_session_liquidity). `next_liq_at = 0`
    # forces a reading on the first poll so the dashboard has a baseline fast.
    liq_days = int(cfg.get("liquidity_baseline_days", 20))
    liq_period = float(cfg.get("liquidity_poll_seconds", 60))
    next_liq_at = 0.0
    # Optional per-symbol footprint row size; falls back to the broker tick size.
    ftick: dict[str, float | None] = {
        m["mt5"]: (m.get("footprint_tick") or _broker_tick(m["mt5"])) for m in cfg["symbols"]
    }
    # Open-position polling. `broker_to_backend` maps MT5 symbol → backend symbol
    # for grouping. `pos_flat` remembers which backend symbols we last reported
    # as flat, so a "now flat" clear is sent exactly once while open positions
    # keep streaming live P&L every period.
    pos_period = float(cfg.get("positions_poll_seconds", 0.25))
    broker_to_backend: dict[str, str] = {m["mt5"]: m["backend"] for m in cfg["symbols"]}
    next_pos_at = 0.0
    pos_flat: dict[str, bool] = {}
    # Auto-close execution gate (read-only by default). Logged loudly when on so
    # it's never a surprise that this collector can place closing orders.
    allow_auto_close = bool(cfg.get("allow_auto_close", False))
    if allow_auto_close:
        logger.warning(
            "allow_auto_close=TRUE — this collector WILL place closing orders when "
            "the backend's profit target fires."
        )
    allow_auto_trade = bool(cfg.get("allow_auto_trade", False))
    is_demo = _account_is_demo()
    if allow_auto_trade:
        logger.warning(
            "allow_auto_trade=TRUE — the scalper bot may OPEN positions (account "
            "is_demo=%s; opening is refused unless demo).",
            is_demo,
        )
    if quote_mode:
        logger.info(
            "tape source: quote-tick flow (no real times&trades on this feed); "
            "footprint ticks: %s",
            {k: v for k, v in ftick.items()},
        )

    ws = None
    while True:
        try:
            if ws is None:
                ws = _connect_backend(url, token)
                # Identify which broker is feeding this stream — the backend
                # stamps every subsequent snapshot with this name so the UI can
                # label each column. Re-sent on every reconnect.
                ws.send(json.dumps({
                    "type": "hello",
                    "source": source_name,
                    "auto_close_enabled": allow_auto_close,
                    "auto_trade_enabled": allow_auto_trade,
                    "account_is_demo": is_demo,
                }))
                # Force a full position resync on (re)connect: mark every symbol
                # not-flat so the next poll reports its true state once (an open
                # list, or a single clear). Without this, a collector restart
                # while flat would leave the backend showing stale positions.
                pos_flat = {b: False for b in broker_to_backend.values()}
                next_pos_at = 0.0
            # Keep the socket alive by replying to server pings before polling,
            # and handle any control command (close_all / close_symbol / open).
            _drain_control(ws, broker_to_backend, allow_auto_close, allow_auto_trade, is_demo)
            for m in cfg["symbols"]:
                backend, broker = m["backend"], m["mt5"]
                if quote_mode:
                    # CFD feed: the broker's DOM is a frozen mirrored demo book,
                    # so derive the live top of book from the quote tick instead.
                    trades, since[broker], mid[broker], quote = _read_quote_flow(
                        backend, broker, since[broker], mid[broker], ftick[broker]
                    )
                    book = (
                        {
                            "type": "book",
                            "symbol": backend,
                            "asof": _now_iso(),
                            "bids": [[quote[0], 0.0]],
                            "asks": [[quote[1], 0.0]],
                        }
                        if quote is not None
                        else None
                    )
                else:
                    book = _read_book(backend, broker, depth)
                    trades, since[broker] = _read_trades(backend, broker, since[broker])
                if book:
                    # Skip unchanged books so we don't flood the backend with a
                    # full snapshot broadcast every poll when nothing moved.
                    sig = json.dumps([book["bids"], book["asks"]])
                    if sig != last_book.get(broker):
                        last_book[broker] = sig
                        ws.send(json.dumps(book))
                if trades:
                    ws.send(json.dumps({"type": "trades", "symbol": backend, "trades": trades}))
            # Periodically recompute + push the session-liquidity reading that
            # feeds the backend's day-outlook gate. Throttled (default 60s) —
            # copy_rates_range over ~3 weeks of M5 bars is heavier than a poll.
            now_mono = time.monotonic()
            if liq_period > 0 and liq_days > 0 and now_mono >= next_liq_at:
                next_liq_at = now_mono + liq_period
                for liq_sym in cfg["symbols"]:
                    try:
                        liq = _read_session_liquidity(
                            liq_sym["backend"], liq_sym["mt5"], liq_days
                        )
                    except Exception as exc:  # never let the gauge break the stream
                        logger.debug("liquidity read failed for %s: %s", liq_sym["mt5"], exc)
                        liq = None
                    if liq:
                        ws.send(json.dumps(liq))
            # Push open positions (live P&L). Throttled below the tick poll. While
            # a symbol has positions we send every period so P&L stays live; when
            # it goes flat we send one empty list to clear, then stay quiet.
            if pos_period > 0 and now_mono >= next_pos_at:
                next_pos_at = now_mono + pos_period
                try:
                    pos_map = _read_positions(broker_to_backend)
                except Exception as exc:  # never let position reads break the stream
                    logger.debug("positions read failed: %s", exc)
                    pos_map = None
                if pos_map is not None:
                    for backend, plist in pos_map.items():
                        if plist:
                            ws.send(json.dumps(
                                {"type": "positions", "symbol": backend, "positions": plist}
                            ))
                            pos_flat[backend] = False
                        elif not pos_flat.get(backend, True):
                            # Transitioned open → flat: clear once.
                            ws.send(json.dumps(
                                {"type": "positions", "symbol": backend, "positions": []}
                            ))
                            pos_flat[backend] = True
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
    # The Windows console defaults to cp1252, which can't encode the arrows/
    # em-dashes used in our log lines (raises UnicodeEncodeError on every emit).
    # Force UTF-8 so logging never trips over a non-ASCII char.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
            pass
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    run(_load_config(args.config))


if __name__ == "__main__":
    main()
