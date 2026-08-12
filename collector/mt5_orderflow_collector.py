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
- The tape source is AUTO-DETECTED per symbol: when the broker publishes real
  times&trades (COPY_TICKS_TRADE with usable prints) we use its flags + real
  volume; otherwise the tape is synthesized from quote ticks. On synthesized
  feeds without per-tick volume, "volume" is a tick COUNT, not traded
  contracts — treat footprint/delta as a pressure proxy. Run diag_forces.py
  to see empirically what your feed exposes.
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

# MT5 tick flags (stable numeric values of the MT5 API's TICK_FLAG_* enum).
# Mirrored as literals so the pure classification helpers below stay importable
# — and unit-testable — on machines without the MetaTrader5 package.
_TICK_FLAG_LAST = 8
_TICK_FLAG_VOLUME = 16
_TICK_FLAG_BUY = 32
_TICK_FLAG_SELL = 64


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- broker server clock vs true UTC -----------------------------------------
# MT5 tick/bar times (`time`, `time_msc`) are in the broker's *server* timezone
# (FTMO runs GMT+2/+3 with EU DST), NOT UTC — and MT5 exposes no API to report
# that zone. Left uncorrected, a print made now is stamped hours in the future,
# which desyncs the tape/footprint from real time and from every `now()`-based
# comparison downstream. We infer the whole-hour offset by comparing a fresh
# tick's server time to the machine's true UTC clock, rounded to the nearest
# hour (broker offsets are always whole hours; rounding absorbs tick lag and
# network latency up to ±30min). Cached and refreshed periodically so a DST
# switch is picked up without a restart. NOTE: this is only for OUTBOUND
# timestamps we stamp as UTC; the `since_msc`/high-water logic stays entirely in
# server-ms and is internally consistent, so it is deliberately left untouched.
_HOUR_MS = 3_600_000
# How often to recompute the offset. DST switches are twice a year, so this only
# needs to be "sometime within the session"; 10 min keeps it cheap and prompt.
_SERVER_OFFSET_REFRESH_SECONDS = 600.0
# Account P&L (day/week/month) refresh cadence. Cheap — one history_deals_get
# over the current month — but banked P&L only moves when a trade closes, so a
# ~30s lag on the top-of-screen cards is fine.
_PNL_REFRESH_SECONDS = 30.0
_server_offset_ms: int = 0


def _refresh_server_offset(brokers: list[str]) -> None:
    """Recompute the server→UTC offset (ms) from the freshest tick across symbols."""
    if mt5 is None:
        return
    now_utc_ms = time.time() * 1000.0
    freshest: float | None = None
    for broker in brokers:
        tick = mt5.symbol_info_tick(broker)
        tmsc = float(getattr(tick, "time_msc", 0.0) or 0.0)
        if tmsc > 0 and (freshest is None or tmsc > freshest):
            freshest = tmsc
    if freshest is None:
        return
    global _server_offset_ms
    offset = round((freshest - now_utc_ms) / _HOUR_MS) * _HOUR_MS
    if offset != _server_offset_ms:
        logger.info("broker server→UTC offset: %+d h", offset // _HOUR_MS)
    _server_offset_ms = offset


def _server_ms_to_utc_iso(tmsc: int) -> str:
    """Convert a broker-server epoch (ms) to a true-UTC ISO-8601 timestamp."""
    return datetime.fromtimestamp((tmsc - _server_offset_ms) / 1000.0, tz=timezone.utc).isoformat()


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
    # By default the collector refuses to open unless the account is a DEMO.
    cfg.setdefault("allow_auto_trade", False)
    # LIVE override: allow the scalper bot to open on a NON-demo account (e.g. an
    # FTMO challenge, which reports CONTEST/REAL — not DEMO). Real orders. Only
    # meaningful together with allow_auto_trade. Default false = demo-only.
    cfg.setdefault("allow_live_auto_trade", False)
    if not cfg.get("backend_ws_url"):
        raise SystemExit("config: 'backend_ws_url' is required")
    if not cfg.get("symbols"):
        raise SystemExit("config: 'symbols' must list at least one mapping")
    return cfg


# --- MT5 session -------------------------------------------------------------


def _init_mt5(cfg: dict[str, Any]) -> tuple[str, int | None]:
    """Attach to the first MT5 terminal in the configured priority list.

    Supports two config shapes:

      "mt5": { "sources": [
          {"name": "FTMO",        "path": "...\\FTMO MetaTrader 5\\terminal64.exe"},
          {"name": "ActivTrades", "path": "...\\ActivTrades MT5\\terminal64.exe"}
      ]}

      "mt5": { "path": "...", "login": ..., "password": "...", "server": "..." }

    The list form is the new preferred shape: each entry is tried in order until
    one succeeds (terminal must be open and logged in). Returns
    ``(source_name, account_login)`` so the backend / UI can show which broker
    and which account are feeding flow.
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
        # Explicit credentials in the config go straight into initialize().
        # A bare "login" (no password) is handled AFTER attach: mt5.login()
        # without a password reuses the credentials saved in the terminal's
        # own database, so the config never needs to hold a secret.
        if src.get("login") and src.get("password"):
            kwargs.update(
                login=int(src["login"]),
                password=src["password"],
                server=src.get("server", ""),
            )
        if mt5.initialize(**kwargs):
            term = mt5.terminal_info()
            acct = mt5.account_info()
            login = getattr(acct, "login", None)

            want = int(src["login"]) if src.get("login") else None
            if want is not None and login != want:
                logger.info("MT5 account is %s; switching to configured %s", login, want)
                if mt5.login(want):
                    acct = mt5.account_info()
                    login = getattr(acct, "login", None)
                if login != want:
                    errors.append(
                        f"{name}: attached to account {login} but could not switch to "
                        f"{want} ({mt5.last_error()}) — log that account into the "
                        "terminal once so its credentials are saved"
                    )
                    try:
                        mt5.shutdown()
                    except Exception:  # pragma: no cover - best-effort cleanup
                        pass
                    continue

            logger.info(
                "MT5 attached: source=%s terminal=%s connected=%s account=%s",
                name,
                getattr(term, "name", "?"),
                getattr(term, "connected", "?"),
                login if login is not None else "?",
            )
            return name, (int(login) if login is not None else None)
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
    if flags & _TICK_FLAG_BUY:
        return "buy"
    if flags & _TICK_FLAG_SELL:
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
                "at": _server_ms_to_utc_iso(tmsc),
                "price": last,
                "volume": vol,
                "side": side,
            }
        )
    return out, high


# Tape-source auto-detection: how far back we probe COPY_TICKS_TRADE, how many
# usable trade prints that window must contain before we trust the real tape,
# and how often a symbol's resolved mode is re-checked while running.
_TAPE_PROBE_MINUTES = 5.0
_TAPE_PROBE_MIN_PRINTS = 5
_TAPE_RECHECK_SECONDS = 300.0


def _usable_trade_tick(flags: int, last: float, volume_real: float, volume: float) -> bool:
    """True when a COPY_TICKS_TRADE tick is a real, usable print: it has a trade
    price AND carries aggressor flags or a size. Some feeds return trade ticks
    that are empty husks (last=0, no flags, no volume) — those prove nothing."""
    if last <= 0.0:
        return False
    return bool(flags & (_TICK_FLAG_BUY | _TICK_FLAG_SELL)) or volume_real > 0.0 or volume > 0.0


def _detect_tape_mode(broker: str) -> str:
    """Resolve 'real' vs 'synth' for one symbol by probing the recent tape.

    'real' when the broker returned at least _TAPE_PROBE_MIN_PRINTS usable trade
    ticks (see _usable_trade_tick) over the last _TAPE_PROBE_MINUTES — enough to
    trust real flags + real volume over the quote-tick proxy. Anything less (an
    empty tape, husk ticks, an MT5 error) falls back to 'synth' so the flow
    never goes dark just because the broker has no times&trades."""
    from_dt = datetime.now(timezone.utc) - timedelta(minutes=_TAPE_PROBE_MINUTES)
    try:
        ticks = mt5.copy_ticks_from(broker, from_dt, 10000, mt5.COPY_TICKS_TRADE)
    except Exception:  # pragma: no cover - defensive
        return "synth"
    if ticks is None or len(ticks) == 0:
        return "synth"
    usable = sum(
        1
        for t in ticks
        if _usable_trade_tick(
            int(t["flags"]), float(t["last"]), float(t["volume_real"]), float(t["volume"])
        )
    )
    return "real" if usable >= _TAPE_PROBE_MIN_PRINTS else "synth"


def _resolve_tape_modes(cfg: dict[str, Any]) -> dict[str, str]:
    """Per-broker-symbol tape mode: 'real' (broker times&trades) or 'synth'
    (quote-tick synthesis). `synthesize_trades_from_quotes` in the config is an
    optional FORCE override: true forces synth, false forces the real tape, and
    absent/null (the recommended default) auto-detects per symbol."""
    force = cfg.get("synthesize_trades_from_quotes")
    modes: dict[str, str] = {}
    for m in cfg["symbols"]:
        broker = m["mt5"]
        if force is True:
            modes[broker] = "synth"
        elif force is False:
            modes[broker] = "real"
        else:
            modes[broker] = _detect_tape_mode(broker)
        logger.info(
            "tape source for %s: %s (%s)",
            broker,
            "quote-tick synthesis" if modes[broker] == "synth" else "real times&trades",
            "forced by config" if force is not None else "auto-detected",
        )
    return modes


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


def _deal_realized(result: Any) -> float:
    """Realized P&L the broker booked for the closing deal of a just-sent order.

    Reads the deal by its ticket (`result.deal`) — more reliable than filtering
    by position right after the close. The deal can take a moment to land in the
    local history cache, so retry briefly. Sums profit + swap + commission =
    what MetaTrader shows for that close."""
    deal_id = int(getattr(result, "deal", 0) or 0)
    if deal_id <= 0:
        return 0.0
    for _ in range(6):
        try:
            deals = mt5.history_deals_get(ticket=deal_id)
        except Exception:  # pragma: no cover - defensive
            deals = None
        if deals:
            return sum(
                float(getattr(d, "profit", 0.0) or 0.0)
                + float(getattr(d, "swap", 0.0) or 0.0)
                + float(getattr(d, "commission", 0.0) or 0.0)
                for d in deals
            )
        time.sleep(0.03)  # deal not in history yet — brief wait (closes are rare)
    logger.warning("Realized P&L unavailable for deal %s (history lag)", deal_id)
    return 0.0


def _read_account_pnl() -> dict[str, Any] | None:
    """Realized account P&L over the calendar day / week / month, ready to send.

    Reads the broker's DEAL history (`history_deals_get`), so it covers EVERY
    closed trade on the account — manual and bot alike — not just what this
    collector opened. Each closed deal's net = profit + commission + swap + fee,
    which is exactly what MetaTrader books. Only BUY/SELL deals count; balance,
    credit and correction operations (deposits, etc.) are skipped.

    Boundaries are in the broker's SERVER time (day rolls at server midnight,
    week starts Monday), matching how MetaTrader reports the account. Returns
    None on an MT5 read error so the caller just retries next cycle."""
    acct = mt5.account_info()
    currency = getattr(acct, "currency", None) if acct is not None else None
    # Live account value from the SAME read: balance = closed/settled (steps on
    # each trade close), equity = balance + floating P&L of open positions.
    balance = float(getattr(acct, "balance", 0.0) or 0.0) if acct is not None else 0.0
    equity = float(getattr(acct, "equity", 0.0) or 0.0) if acct is not None else 0.0
    # server wall-clock now = UTC + the broker offset we already track.
    server_now = (
        datetime.now(timezone.utc) + timedelta(milliseconds=_server_offset_ms)
    ).replace(tzinfo=None)
    day_start = server_now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())  # back to Monday
    month_start = day_start.replace(day=1)
    # Fetch the widest window once (the month); day/week are filtered from it.
    try:
        deals = mt5.history_deals_get(month_start, server_now + timedelta(minutes=1))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("history_deals_get failed: %s", exc)
        return None
    if deals is None:
        return None
    # deal.time is a POSIX stamp of the server wall-clock; compare against the
    # boundaries stamped the same way (naive server dt read as if it were UTC).
    day_epoch = day_start.replace(tzinfo=timezone.utc).timestamp()
    week_epoch = week_start.replace(tzinfo=timezone.utc).timestamp()
    day = week = month = 0.0
    for d in deals:
        if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            continue  # skip balance / credit / correction operations
        net = (
            float(getattr(d, "profit", 0.0) or 0.0)
            + float(getattr(d, "commission", 0.0) or 0.0)
            + float(getattr(d, "swap", 0.0) or 0.0)
            + float(getattr(d, "fee", 0.0) or 0.0)
        )
        month += net
        if d.time >= week_epoch:
            week += net
        if d.time >= day_epoch:
            day += net
    return {
        "type": "account_pnl",
        "day": round(day, 2),
        "week": round(week, 2),
        "month": round(month, 2),
        "currency": currency,
        "balance": round(balance, 2),
        "equity": round(equity, 2),
    }


def _read_balance_history() -> dict[str, Any] | None:
    """Per-trade balance curve reconstructed from the broker's DEAL history.

    Walks every closed BUY/SELL deal of the current month (same window as the
    P&L cards — manual AND bot trades) in server-clock order, stepping a running
    balance by each deal's net. The running balance is anchored so the LAST step
    equals the account's current balance, so the curve is exact regardless of
    deals before the window. Each point carries that deal's `pnl` so the UI can
    show the variation per trade. Returns None on an MT5 read error."""
    acct = mt5.account_info()
    if acct is None:
        return None
    currency = getattr(acct, "currency", None)
    balance = float(getattr(acct, "balance", 0.0) or 0.0)
    server_now = (
        datetime.now(timezone.utc) + timedelta(milliseconds=_server_offset_ms)
    ).replace(tzinfo=None)
    month_start = server_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        deals = mt5.history_deals_get(month_start, server_now + timedelta(minutes=1))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("history_deals_get (balance) failed: %s", exc)
        return None
    if deals is None:
        return None
    trades: list[tuple[float, float]] = []
    for d in deals:
        if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            continue  # skip balance / credit / correction operations
        net = (
            float(getattr(d, "profit", 0.0) or 0.0)
            + float(getattr(d, "commission", 0.0) or 0.0)
            + float(getattr(d, "swap", 0.0) or 0.0)
            + float(getattr(d, "fee", 0.0) or 0.0)
        )
        trades.append((float(d.time), net))
    trades.sort(key=lambda x: x[0])
    # Anchor: balance right before the first in-window deal. Stepping forward
    # from it lands exactly on the account's current balance.
    running = balance - sum(net for _, net in trades)
    points: list[dict[str, Any]] = []
    for t, net in trades:
        running += net
        points.append(
            {
                "ts": _server_ms_to_utc_iso(int(t * 1000)),  # deal.time is server-epoch seconds
                "balance": round(running, 2),
                "pnl": round(net, 2),
            }
        )
    return {
        "type": "balance_history",
        "currency": currency,
        "balance": round(balance, 2),
        "points": points,
    }


def _close_all_positions(broker_symbols: set[str] | None = None) -> dict[str, Any]:
    """Close open positions (fresh read). With `broker_symbols`, only those MT5
    symbols are closed (the per-asset button); None closes everything (the
    profit-target auto-close). Returns a result summary the backend records and
    shows in the UI, including `pnl` = the broker's actual realized total of the
    closed positions. Best-effort: keeps going past a failure."""
    raw = mt5.positions_get()
    if raw is None:
        return {"ok": False, "closed": 0, "pnl": 0.0, "error": "positions_get() retornou None"}
    closed = 0
    pnl = 0.0
    errors: list[str] = []
    for p in raw:
        if broker_symbols is not None and p.symbol not in broker_symbols:
            continue
        result = _close_position(p)
        if result is not None and getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            closed += 1
            pnl += _deal_realized(result)  # broker-booked realized of the close
            logger.info("Auto-close: closed %s #%s", p.symbol, p.ticket)
        else:
            rc = getattr(result, "retcode", "?")
            cm = getattr(result, "comment", "")
            errors.append(f"{p.symbol}#{p.ticket}: retcode={rc} {cm}")
            logger.warning("Auto-close FAILED for %s #%s: retcode=%s %s", p.symbol, p.ticket, rc, cm)
    return {"ok": not errors, "closed": closed, "pnl": pnl, "errors": errors}


def _move_to_breakeven(broker_symbols: set[str] | None = None) -> dict[str, Any]:
    """Move each open position's stop-loss to its entry price (breakeven). With
    `broker_symbols`, only those MT5 symbols; None = all. Best-effort: keeps going
    past a failure and reports a summary the backend surfaces in the UI.

    An SL only belongs at entry once price has moved in the trade's favour — for a
    still-underwater position the entry sits on the wrong side of the market and
    the broker rejects it — so those are skipped rather than sent (and counted so
    the UI can say "nothing to lock in yet")."""
    raw = mt5.positions_get()
    if raw is None:
        return {"ok": False, "moved": 0, "skipped": 0, "error": "positions_get() retornou None"}
    moved = 0
    skipped = 0
    errors: list[str] = []
    for p in raw:
        if broker_symbols is not None and p.symbol not in broker_symbols:
            continue
        entry = float(p.price_open)
        current = float(p.price_current)
        # Skip positions not (yet) in profit — SL at entry would be invalid there.
        if p.type == mt5.POSITION_TYPE_BUY and current <= entry:
            skipped += 1
            continue
        if p.type == mt5.POSITION_TYPE_SELL and current >= entry:
            skipped += 1
            continue
        # Already at (or better than) breakeven? Leave it — don't loosen a trailed SL.
        sl = float(p.sl)
        if p.type == mt5.POSITION_TYPE_BUY and sl >= entry and sl != 0.0:
            skipped += 1
            continue
        if p.type == mt5.POSITION_TYPE_SELL and 0.0 < sl <= entry:
            skipped += 1
            continue
        result = mt5.order_send(
            {
                "action": mt5.TRADE_ACTION_SLTP,
                "symbol": p.symbol,
                "position": int(p.ticket),
                "sl": entry,
                "tp": float(p.tp),  # keep the existing take-profit
            }
        )
        if result is not None and getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            moved += 1
            logger.info("Breakeven: moved SL to entry for %s #%s", p.symbol, p.ticket)
        else:
            rc = getattr(result, "retcode", "?")
            cm = getattr(result, "comment", "")
            errors.append(f"{p.symbol}#{p.ticket}: retcode={rc} {cm}")
            logger.warning(
                "Breakeven FAILED for %s #%s: retcode=%s %s", p.symbol, p.ticket, rc, cm
            )
    return {"ok": not errors, "moved": moved, "skipped": skipped, "errors": errors}


def _place_pending(broker: str, side: str, lots: float, price: float) -> Any:
    """Place one limit order (the grid): BUY_LIMIT below / SELL_LIMIT above the
    market. Pending orders use FILLING_RETURN. Returns the order_send result."""
    order_type = mt5.ORDER_TYPE_BUY_LIMIT if side == "buy" else mt5.ORDER_TYPE_SELL_LIMIT
    req = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": broker,
        "volume": float(lots),
        "type": order_type,
        "price": float(price),
        "deviation": 50,
        "comment": "trading-buddy grid",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    return mt5.order_send(req)


def _place_grid(broker: str, side: str, lots: float, levels: list[float]) -> dict[str, Any]:
    """Place the grid limit orders. Best-effort; reports how many landed."""
    placed = 0
    errors: list[str] = []
    for price in levels:
        r = _place_pending(broker, side, lots, price)
        if r is not None and getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            placed += 1
        else:
            errors.append(f"{broker}@{price}: retcode={getattr(r,'retcode','?')} "
                          f"{getattr(r,'comment','')}")
    return {"placed": placed, "errors": errors}


def _marker_order_type(side: str, target: float, market: float) -> Any:
    """Pick the pending order type so the marker is valid on WHICHEVER side of
    the market it sits: a sell above market is a SELL_LIMIT, below is a
    SELL_STOP; a buy below is a BUY_LIMIT, above is a BUY_STOP."""
    if side == "sell":
        return mt5.ORDER_TYPE_SELL_LIMIT if target >= market else mt5.ORDER_TYPE_SELL_STOP
    return mt5.ORDER_TYPE_BUY_LIMIT if target <= market else mt5.ORDER_TYPE_BUY_STOP


_MARKER_COMMENT = "trading-buddy mark"
# Magic number stamped on every marker so we can find + replace our OWN markers
# reliably. We can't match on the comment: the broker truncates it to ~16 chars
# (FTMO stores "trading-buddy ma"), but `magic` is a full integer it never alters.
_MARKER_MAGIC = 770077


def _cancel_markers_for(broker: str) -> int:
    """Cancel this collector's own resting MARKERS on one symbol (pending orders
    stamped with `_MARKER_MAGIC`), leaving any hand-placed orders untouched.
    Called before dropping a fresh marker so the auto-placing analysis keeps
    exactly one marker per symbol instead of stacking 0.01 orders each run."""
    raw = mt5.orders_get(symbol=broker)
    if not raw:
        return 0
    cancelled = 0
    for o in raw:
        if int(getattr(o, "magic", 0) or 0) != _MARKER_MAGIC:
            continue  # not ours — never cancel the user's own pendings
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(o.ticket)})
        if r is not None and getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            cancelled += 1
    return cancelled


def _place_marker(
    broker: str, side: str, price: float | None, offset: float | None, lots: float
) -> tuple[Any, float]:
    """Place one tiny pending order PURELY to draw the entry line on the MT5
    chart (the MetaTrader5 Python API can't draw chart objects, so a resting
    order at min lot is the visual marker). Resolves the target from an absolute
    `price` or a signed `offset` in price-points from the current market, snaps
    it to the symbol's tick grid, clears the broker's minimum stop distance, and
    picks LIMIT vs STOP so it's always accepted. Returns (order_send result,
    resolved target price)."""
    info = mt5.symbol_info(broker)
    tick = mt5.symbol_info_tick(broker)
    bid = float(getattr(tick, "bid", 0.0) or 0.0)
    ask = float(getattr(tick, "ask", 0.0) or 0.0)
    market = (bid + ask) / 2.0 if (bid and ask) else (bid or ask)
    target = float(price) if price is not None else market + float(offset or 0.0)
    tsize = float(getattr(info, "trade_tick_size", 0.0) or getattr(info, "point", 0.0) or 0.0)
    point = float(getattr(info, "point", 0.0) or 0.0)

    def _snap(p: float) -> float:
        return round(round(p / tsize) * tsize, 10) if tsize > 0 else p

    target = _snap(target)
    # A pending order must clear the broker's minimum stop distance from market;
    # a marker too close would be rejected, so nudge it just past that gap
    # (keeping the side the caller intended).
    min_gap = float(getattr(info, "trade_stops_level", 0.0) or 0.0) * point
    if min_gap > 0 and abs(target - market) < min_gap:
        direction = 1.0 if target >= market else -1.0
        target = _snap(market + direction * (min_gap + (tsize or point)))
    req = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": broker,
        "volume": float(lots),
        "type": _marker_order_type(side, target, market),
        "price": float(target),
        "deviation": 50,
        "magic": _MARKER_MAGIC,
        "comment": _MARKER_COMMENT,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    return mt5.order_send(req), target


def _cancel_pending_for(broker_symbols: set[str] | None) -> dict[str, Any]:
    """Cancel resting (pending) orders. With `broker_symbols`, only those; None =
    all. Used to clean up unfilled grid orders when a trade exits."""
    raw = mt5.orders_get()
    if raw is None:
        return {"cancelled": 0, "errors": []}
    cancelled = 0
    errors: list[str] = []
    for o in raw:
        if broker_symbols is not None and o.symbol not in broker_symbols:
            continue
        r = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(o.ticket)})
        if r is not None and getattr(r, "retcode", None) == mt5.TRADE_RETCODE_DONE:
            cancelled += 1
        else:
            errors.append(f"{o.symbol}#{o.ticket}: retcode={getattr(r,'retcode','?')}")
    return {"cancelled": cancelled, "errors": errors}


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


def _read_candles(backend: str, broker: str, count: int) -> dict[str, Any] | None:
    """Last `count` M5 bars (newest last; the final bar is still forming).

    Bar times are converted from the broker's server clock to true UTC with
    the shared `_server_offset_ms`, so the backend can line them up with every
    other UTC timestamp it holds. Feeds the Bollinger-projection tab.
    """
    if mt5 is None:
        return None
    rates = mt5.copy_rates_from_pos(broker, mt5.TIMEFRAME_M5, 0, count)
    if rates is None or len(rates) == 0:
        return None
    bars = [
        {
            "ts": _server_ms_to_utc_iso(int(r["time"]) * 1000),
            "o": float(r["open"]),
            "h": float(r["high"]),
            "l": float(r["low"]),
            "c": float(r["close"]),
            "v": float(r["tick_volume"]),
        }
        for r in rates
    ]
    return {"type": "candles", "symbol": backend, "asof": _now_iso(), "bars": bars}


def _quantize(price: float, tick: float | None) -> float:
    """Snap a price to the footprint row grid so a continuous quote feed doesn't
    fragment into thousands of distinct footprint cells. No tick → unchanged."""
    if not tick or tick <= 0:
        return price
    return round(round(price / tick) * tick, 10)


def _classify_quote_tick(
    flags: int, last: float, bid: float, ask: float, prev_mid: float | None, mid: float
) -> str | None:
    """Aggressor side for one quote tick, or None when it carries no direction.

    Evidence in order of strength (the Lee-Ready rule adapted to this feed):
    1. Broker aggressor flags — rare on quote streams, but authoritative.
    2. Quote rule on a FRESH `last` (only when TICK_FLAG_LAST says this tick
       carried a trade — otherwise `last` is stale, carried forward from an
       earlier deal, and says nothing about this quote): a print at/above the
       ask is buyers lifting the offer, at/below the bid is sellers hitting it.
       Inside the spread (or a stale last) → 3.
    3. Tick test on the mid price: uptick = buy, downtick = sell. Unchanged mid
       with no stronger evidence → None (not a directional print).
    """
    if flags & _TICK_FLAG_BUY:
        return "buy"
    if flags & _TICK_FLAG_SELL:
        return "sell"
    if (flags & _TICK_FLAG_LAST) and last > 0.0:
        if ask and last >= ask:
            return "buy"
        if bid and last <= bid:
            return "sell"
    if prev_mid is not None and mid != prev_mid:
        return "buy" if mid > prev_mid else "sell"
    return None


def _quote_tick_volume(volume_real: float, volume: float) -> float:
    """Size of one synthesized print. Uses the feed's real per-tick volume when
    it carries one (volume_real, else volume); only when BOTH are zero does it
    fall back to 1.0 — at that point the tape is honestly a tick-COUNT proxy
    (pressure = count of directional ticks), not traded contracts. Most CFD
    quote streams are the latter; the fallback keeps delta meaningful anyway."""
    if volume_real > 0.0:
        return volume_real
    if volume > 0.0:
        return volume
    return 1.0


def _read_quote_flow(
    backend: str, broker: str, since_msc: int, last_mid: float | None, tick: float | None
) -> tuple[list[dict[str, Any]], int, float | None, tuple[float, float] | None]:
    """Synthesize a buy/sell tape from quote ticks when the broker has no
    times&trades (the common CFD case: COPY_TICKS_TRADE is empty).

    Aggressor is inferred per tick by `_classify_quote_tick` (broker flags →
    last vs bid/ask → mid-price tick test). Volume is the feed's real per-tick
    volume when it exposes one; otherwise each directional tick counts as 1, in
    which case the pressure signal (delta) is a tick COUNT, not traded
    contracts (see `_quote_tick_volume`). Returns
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
        last = float(t["last"])
        flags = int(t["flags"])
        side = _classify_quote_tick(flags, last, bid, ask, prev, mid)
        if side is not None:
            # Print at the traded price only when THIS tick carried a fresh
            # trade (TICK_FLAG_LAST); otherwise `last` is stale, so price at the
            # side of the book the aggressor consumed (buy lifts the ask, sell
            # hits the bid) — matching the backend's delta convention.
            fresh_last = bool(flags & _TICK_FLAG_LAST) and last > 0.0
            price = last if fresh_last else (ask if side == "buy" else bid)
            out.append(
                {
                    "at": _server_ms_to_utc_iso(tmsc),
                    "price": _quantize(price, tick),
                    "volume": _quote_tick_volume(float(t["volume_real"]), float(t["volume"])),
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
    allow_live: bool = False,
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
      - `mark` (a min-lot entry marker on the chart) — gated by `allow_auto_trade`.
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
        if not (allow_auto_trade and (is_demo or allow_live)):
            reason = (
                "allow_auto_trade=false"
                if not allow_auto_trade
                else "conta não é demo (use allow_live_auto_trade=true pra liberar)"
            )
            logger.warning("Refusing open: %s", reason)
            ws.send(json.dumps({"type": "open_result", "ok": False, "symbol": backend_sym,
                                "error": reason}))
            return
        result = _open_position(brokers[0], side, lots)
        ok = result is not None and getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE
        logger.info("Bot open %s %s %s → ok=%s", side, brokers[0], lots, ok)
        # Grid: place the limit orders below (buy) / above (sell), if requested.
        grid = cmd.get("grid") or []
        if ok and grid:
            g = _place_grid(brokers[0], side, lots, [float(x) for x in grid])
            logger.info("Grid for %s: placed %s, errors %s", brokers[0], g["placed"], g["errors"])
        # Fill price for the trade-history record: prefer the executed deal price.
        fill_price = float(getattr(result, "price", 0.0) or 0.0) if ok else None
        ws.send(json.dumps({"type": "open_result", "ok": ok, "symbol": backend_sym, "side": side,
                            "lots": float(lots),
                            "price": fill_price,
                            "ticket": getattr(result, "order", None) if ok else None,
                            "error": None if ok else f"retcode={getattr(result,'retcode','?')} "
                                                     f"{getattr(result,'comment','')}"}))
        return

    if ctype == "mark":
        # Draw an entry-marker line on the chart: a min-lot pending order at the
        # recommended zone. Rides the OPEN gate (it's an order_send that can
        # fill), but — unlike the autonomous scalper — is user-initiated and NOT
        # demo-restricted: Diego asks for it explicitly, at 0.01.
        backend_sym = cmd.get("symbol")
        side = cmd.get("side")
        lots = float(cmd.get("lots", 0.01) or 0.01)
        price = cmd.get("price")
        offset = cmd.get("offset")
        brokers = [b for b, be in broker_to_backend.items() if be == backend_sym]
        if not brokers or side not in ("buy", "sell") or lots <= 0 or (price is None and offset is None):
            ws.send(json.dumps({"type": "mark_result", "ok": False, "symbol": backend_sym,
                                "error": f"comando mark inválido: {cmd}"}))
            return
        if not allow_auto_trade:
            logger.warning("Refusing mark: allow_auto_trade is false on this collector")
            ws.send(json.dumps({"type": "mark_result", "ok": False, "symbol": backend_sym,
                                "error": "allow_auto_trade=false no collector"}))
            return
        # Replace any prior marker on this symbol so repeated analysis runs keep a
        # single marker (never touches the user's own pending orders).
        replaced = _cancel_markers_for(brokers[0])
        result, target = _place_marker(
            brokers[0], side,
            float(price) if price is not None else None,
            float(offset) if offset is not None else None,
            lots,
        )
        ok = result is not None and getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE
        logger.info("Mark %s %s @%.5g lots=%s replaced=%d → ok=%s",
                    side, brokers[0], target, lots, replaced, ok)
        ws.send(json.dumps({"type": "mark_result", "ok": ok, "symbol": backend_sym, "side": side,
                            "price": target, "lots": lots, "replaced": replaced,
                            "ticket": getattr(result, "order", None) if ok else None,
                            "error": None if ok else f"retcode={getattr(result,'retcode','?')} "
                                                     f"{getattr(result,'comment','')}"}))
        return

    if ctype == "cancel_pending":
        backend_sym = cmd.get("symbol")
        brokers_set = {b for b, be in broker_to_backend.items() if be == backend_sym}
        if not allow_auto_close:
            return  # closing/cancelling needs the close gate
        res = _cancel_pending_for(brokers_set or None)
        logger.info("Cancel pending %s: %s", backend_sym, res)
        return

    if ctype == "breakeven_symbol":
        backend_sym = cmd.get("symbol")
        brokers_set = {b for b, be in broker_to_backend.items() if be == backend_sym}
        if not brokers_set:
            ws.send(json.dumps({"type": "breakeven_result", "ok": False, "moved": 0,
                                "error": f"símbolo desconhecido: {backend_sym}"}))
            return
        # Modifying an SL is a protective change, but it's still an order_send, so
        # it rides the same execution gate as closing.
        if not allow_auto_close:
            logger.warning("Refusing breakeven: allow_auto_close is false on this collector")
            ws.send(json.dumps({"type": "breakeven_result", "ok": False, "moved": 0,
                                "symbol": backend_sym, "error": "allow_auto_close=false no collector"}))
            return
        res = _move_to_breakeven(brokers_set)
        logger.info("Breakeven %s: %s", backend_sym, res)
        ws.send(json.dumps({"type": "breakeven_result", "symbol": backend_sym, **res}))
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
    # Also cancel any resting grid orders for the same symbol(s), so closing a
    # trade never leaves orphaned limits hanging.
    cancel = _cancel_pending_for(target_brokers)
    if cancel["cancelled"] or cancel["errors"]:
        logger.info("Cancelled %s pending on close (%s)", cancel["cancelled"], cancel["errors"])
    # Echo back who asked + why + which symbol/side so the backend can record
    # ONLY bot closes in the trade history, with the broker's real `pnl`.
    echo = {k: cmd.get(k) for k in ("origin", "reason", "symbol", "side") if cmd.get(k) is not None}
    ws.send(json.dumps({"type": "autoclose_result", **result, **echo}))


def run(cfg: dict[str, Any]) -> None:
    if create_connection is None:
        raise SystemExit("websocket-client not installed. `pip install websocket-client`.")
    source_name, account_login = _init_mt5(cfg)
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
    # Tape source per symbol: 'real' broker times&trades when the feed has them,
    # 'synth' quote-tick synthesis otherwise. Auto-detected at startup (unless
    # the config forces a mode) and re-checked every _TAPE_RECHECK_SECONDS so a
    # feed that starts publishing trades — or dries up — flips without a
    # restart. `mid` holds the last mid price per symbol for the synth path's
    # tick test.
    tape_mode = _resolve_tape_modes(cfg)
    force_mode = cfg.get("synthesize_trades_from_quotes")
    next_mode_at = time.monotonic() + _TAPE_RECHECK_SECONDS
    # Broker→UTC clock offset (see _refresh_server_offset). Refreshed on its own
    # cadence — independent of the tape/liquidity toggles — so tape & footprint
    # timestamps stay true-UTC and a DST switch is absorbed without a restart.
    # `next_offset_at = 0` forces a reading on the first poll.
    all_brokers = [m["mt5"] for m in cfg["symbols"]]
    next_offset_at = 0.0
    mid: dict[str, float | None] = {m["mt5"]: None for m in cfg["symbols"]}
    # Liquidity gauge cadence (see _read_session_liquidity). `next_liq_at = 0`
    # forces a reading on the first poll so the dashboard has a baseline fast.
    liq_days = int(cfg.get("liquidity_baseline_days", 20))
    liq_period = float(cfg.get("liquidity_poll_seconds", 60))
    next_liq_at = 0.0
    # M5 candle push cadence (Bollinger-projection tab). `next_candles_at = 0`
    # forces a first push so the chart draws as soon as the stream is up.
    cand_period = float(cfg.get("candles_poll_seconds", 5))
    cand_bars = int(cfg.get("candles_bars", 120))
    next_candles_at = 0.0
    # Account P&L (day/week/month) cadence. `next_pnl_at = 0` forces a first read
    # so the top-of-screen cards populate as soon as the stream is up.
    next_pnl_at = 0.0
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
    allow_live = bool(cfg.get("allow_live_auto_trade", False))
    is_demo = _account_is_demo()
    if allow_auto_trade:
        logger.warning(
            "allow_auto_trade=TRUE — the scalper bot may OPEN positions (account "
            "is_demo=%s, allow_live_auto_trade=%s; opening is refused unless demo "
            "OR the live override is on).",
            is_demo,
            allow_live,
        )
    if allow_auto_trade and allow_live and not is_demo:
        logger.warning(
            "allow_live_auto_trade=TRUE on a NON-demo account — the bot will open "
            "REAL positions on this account."
        )
    logger.info("footprint ticks: %s", {k: v for k, v in ftick.items()})

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
                    "account": account_login,
                    "auto_close_enabled": allow_auto_close,
                    "auto_trade_enabled": allow_auto_trade,
                    "account_is_demo": is_demo,
                    "auto_trade_live_ok": allow_live,
                }))
                # Force a full position resync on (re)connect: mark every symbol
                # not-flat so the next poll reports its true state once (an open
                # list, or a single clear). Without this, a collector restart
                # while flat would leave the backend showing stale positions.
                pos_flat = {b: False for b in broker_to_backend.values()}
                next_pos_at = 0.0
            # Keep the socket alive by replying to server pings before polling,
            # and handle any control command (close_all / close_symbol / open).
            _drain_control(
                ws, broker_to_backend, allow_auto_close, allow_auto_trade, is_demo, allow_live
            )
            # Keep the server→UTC offset fresh before stamping this poll's tape.
            if time.monotonic() >= next_offset_at:
                next_offset_at = time.monotonic() + _SERVER_OFFSET_REFRESH_SECONDS
                _refresh_server_offset(all_brokers)
            for m in cfg["symbols"]:
                backend, broker = m["backend"], m["mt5"]
                if tape_mode[broker] == "synth":
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
            now_mono = time.monotonic()
            # Re-check the tape source periodically (auto mode only): a feed can
            # start publishing real trades mid-session, or a real tape can dry
            # up — either way we switch paths and log it, no restart needed.
            if force_mode is None and now_mono >= next_mode_at:
                next_mode_at = now_mono + _TAPE_RECHECK_SECONDS
                for m in cfg["symbols"]:
                    new_mode = _detect_tape_mode(m["mt5"])
                    if new_mode != tape_mode[m["mt5"]]:
                        logger.info(
                            "tape source for %s switched: %s → %s",
                            m["mt5"],
                            tape_mode[m["mt5"]],
                            new_mode,
                        )
                        tape_mode[m["mt5"]] = new_mode
                        mid[m["mt5"]] = None  # fresh tick-test baseline for synth
            # Periodically recompute + push the session-liquidity reading that
            # feeds the backend's day-outlook gate. Throttled (default 60s) —
            # copy_rates_range over ~3 weeks of M5 bars is heavier than a poll.
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
            # Push M5 candle history (Bollinger-projection tab). Own cadence —
            # a 5m chart doesn't need the tick poll rate.
            if cand_period > 0 and now_mono >= next_candles_at:
                next_candles_at = now_mono + cand_period
                for m in cfg["symbols"]:
                    try:
                        cand = _read_candles(m["backend"], m["mt5"], cand_bars)
                    except Exception as exc:  # never let candles break the stream
                        logger.debug("candles read failed for %s: %s", m["mt5"], exc)
                        cand = None
                    if cand:
                        ws.send(json.dumps(cand))
            # Push realized account P&L (day/week/month). Own slow cadence — it
            # only moves when a trade closes, and the read scans the whole month.
            if now_mono >= next_pnl_at:
                next_pnl_at = now_mono + _PNL_REFRESH_SECONDS
                try:
                    pnl = _read_account_pnl()
                except Exception as exc:  # never let the P&L read break the stream
                    logger.debug("account P&L read failed: %s", exc)
                    pnl = None
                if pnl is not None:
                    ws.send(json.dumps(pnl))
                # Per-trade balance curve (reconstructed from deal history) —
                # same slow cadence; only changes when a trade closes.
                try:
                    bal_hist = _read_balance_history()
                except Exception as exc:  # never let it break the stream
                    logger.debug("balance history read failed: %s", exc)
                    bal_hist = None
                if bal_hist is not None:
                    ws.send(json.dumps(bal_hist))
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
