"""Order-flow WebSocket + REST surface.

Three endpoints:

- ``WS /ws/ingest/orderflow`` — the Windows MT5 collector connects here (with
  a shared token) and pushes ``book`` / ``trade`` / ``trades`` messages. The
  handler feeds the aggregator and re-broadcasts the updated per-symbol
  snapshot to browsers.
- ``WS /ws/orderflow`` — browsers subscribe; the broadcaster replays the
  latest snapshot per symbol on connect, then streams live updates.
- ``GET /api/orderflow`` — latest snapshot per symbol (initial load / tests).

The aggregator + ingest token are built once from settings at import time, so
the channel is fully configured before the first collector connects.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from adapters.balance_history import BalanceHistory
from adapters.tape_recorder import TapeRecorder
from api.orderflow_broadcaster import orderflow_broadcaster
from api.routes.performance import trade_history
from core.enums import AssetSymbol
from core.models import (
    AccountBalanceHistory,
    AccountPnl,
    AutoCloseStatus,
    BalanceStep,
    BandScenario,
    BotStatus,
    BotTrade,
    CashFlow,
    ClosedTrade,
    EquityPoint,
    IntradayBar,
    OrderFlowSnapshot,
    Position,
    SessionLiquidity,
)
from settings import get_settings
from use_cases.aggregate_orderflow import OrderFlowAggregator
from use_cases.assess_trade_signals import assess_trade_signals
from use_cases.autoclose import should_autoclose
from use_cases.orderflow_wire import (
    parse_book,
    parse_dt,
    parse_liquidity,
    parse_position,
    parse_symbol,
    parse_trade,
)
from use_cases.project_band_path import project_band_path
from use_cases.scalper import (
    LOCK_GIVEBACK,
    LOCK_MIN_USD,
    REARM_COOLDOWN_S,
    SYMBOL_STOP_USD,
    THIN_RATIO,
    Direction,
    grid_breach_price,
    grid_levels,
    region_broken,
    should_open,
    symbol_stopped,
)
from use_cases.trade_signal import (
    compute_flow_signal,
    held_side,
    signal_entry_direction,
    signal_says_reverse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["orderflow"])


def _build_aggregator() -> OrderFlowAggregator:
    settings = get_settings()
    symbols: list[AssetSymbol] = []
    for raw in settings.orderflow_symbol_list:
        try:
            symbols.append(AssetSymbol(raw))
        except ValueError:
            logger.warning("Ignoring unknown ORDERFLOW_SYMBOLS entry: %s", raw)
    return OrderFlowAggregator(
        symbols=symbols,
        footprint_interval_seconds=settings.orderflow_footprint_interval_seconds,
        footprint_bars=settings.orderflow_footprint_bars,
        tape_maxlen=settings.orderflow_tape_maxlen,
    )


# Process-wide singleton. The ingest handler mutates it; the REST route reads it.
aggregator = _build_aggregator()


def _build_recorder() -> TapeRecorder | None:
    """Raw-tape recorder (backtest input), or None when disabled in settings."""
    raw = get_settings().orderflow_record_dir.strip()
    return TapeRecorder(Path(raw)) if raw else None


# Records every data message the collector pushes (see TapeRecorder docstring).
_tape_recorder = _build_recorder()

# Latest per-symbol session-liquidity reading pushed by the collector. Lives in
# the same process as the tick loop (API + loop share a process), so the
# day-outlook assessor reads it directly — no DB / cache round-trip needed.
_liquidity_store: dict[AssetSymbol, SessionLiquidity] = {}

# Latest open positions per symbol pushed by the collector (read-only mirror of
# MT5). Lives in the same process as the ingest loop, like `_liquidity_store`,
# and is stamped onto each symbol's snapshot. An explicit empty list means the
# collector reported the symbol is flat (so a closed trade clears from the UI).
_positions_store: dict[AssetSymbol, list[Position]] = {}

# M5 candles per symbol pushed by the collector (newest last; the final bar is
# the one still forming). Feeds the Bollinger-projection tab over REST — candles
# do NOT ride the order-flow snapshot, the UI polls them.
#
# Pushes are MERGED by bar timestamp rather than replacing the list: the live
# push carries only the recent bars (for the chart), while a slower deep push
# backfills history, and the band scenario needs as much of it as it can get.
_candles_store: dict[AssetSymbol, list[IntradayBar]] = {}

# ~7 days of M5 bars. Caps memory while leaving plenty of history for the
# scenario's analog search.
_MAX_CANDLES = 2000

# Bars the chart itself draws — the default slice served to the UI, so the deep
# history never has to travel over the wire.
_CHART_CANDLES = 120


def _merge_candles(symbol: AssetSymbol, incoming: list[IntradayBar]) -> None:
    """Fold a candle push into the stored history, newest last.

    Keyed by bar timestamp so the still-forming last bar is overwritten on
    every push (not appended twice) and a deep backfill slots in behind the
    bars already held.
    """
    merged = {bar.timestamp: bar for bar in _candles_store.get(symbol, ())}
    merged.update({bar.timestamp: bar for bar in incoming})
    ordered = [merged[ts] for ts in sorted(merged)]
    _candles_store[symbol] = ordered[-_MAX_CANDLES:]


def latest_liquidity() -> dict[AssetSymbol, SessionLiquidity]:
    """Snapshot of the most recent MT5 liquidity reading per symbol.

    Read by `RunDashboardTickUseCase` to feed the day-outlook gate. Returns a
    shallow copy so the caller can iterate without racing the ingest handler.
    """
    return dict(_liquidity_store)


def latest_candles() -> dict[AssetSymbol, list[IntradayBar]]:
    """The M5 bars the collector has pushed so far, per symbol.

    Read by `RunDashboardTickUseCase`, which prefers these over yfinance for
    three reasons: they are the broker's own bars (the same feed the trader has
    on screen), they carry MT5 tick volume — so VWAP works on EURUSD and GER40,
    where Yahoo reports zero volume — and they are live instead of ~15 minutes
    late. Copies the lists so the caller can iterate without racing a push.
    """
    return {symbol: list(bars) for symbol, bars in _candles_store.items()}


# --- wire-format parsing -----------------------------------------------------


# The wire parsers moved to `use_cases/orderflow_wire.py` so the tape replay
# (backtest) parses recorded sessions exactly like the live ingest does.
_parse_dt = parse_dt
_parse_symbol = parse_symbol
_parse_book = parse_book
_parse_liquidity = parse_liquidity
_parse_position = parse_position
_parse_trade = parse_trade


# Connection-level state set by the collector's `hello` message. One collector
# per backend process today, so a module-level slot is enough; if we ever
# multiplex collectors per-symbol we'd promote this into the aggregator.
_current_source: str | None = None
_current_account: int | None = None
# Whether the collector permits opening orders (allow_auto_trade in its config).
# Gates the manual chart-marker endpoint — a marker is an order_send that can
# fill, so it needs the same open capability the scalper does (but, being
# user-initiated and min-lot, it is NOT demo-restricted). Mirrored from `hello`.
_auto_trade_enabled: bool = False
# Last chart-marker outcome reported by the collector (for logs / status).
_mark_last_result: str | None = None
# Latest realized account P&L (day/week/month) pushed by the collector. None
# until the first `account_pnl` message arrives.
_account_pnl: AccountPnl | None = None


def _build_balance_history() -> BalanceHistory:
    """Balance/equity series store — persisted to JSONL unless disabled."""
    raw = get_settings().account_balance_dir.strip()
    return BalanceHistory(Path(raw) if raw else None)


# Rolling balance/equity series (fed from the `account_pnl` message, which also
# carries balance/equity). Served over REST to the UI balance chart.
_balance_history = _build_balance_history()


class _AutoCloseState:
    """Mutable whole-account auto-close state. One per process (one collector).

    The collector is the only thing that can execute, so `enabled` mirrors its
    `allow_auto_close` capability from the `hello` message; arming is refused
    when the collector can't execute. `armed` is one-shot — cleared on fire.
    """

    def __init__(self) -> None:
        self.enabled: bool = False  # collector permits execution (allow_auto_close)
        self.armed: bool = False
        self.target_usd: float | None = None
        # Auto-arm: keep the account auto-close on by default — arm on collector
        # connect and re-arm after each fire. A manual disarm turns this off.
        self.auto_arm: bool = False
        self.cooling: bool = False  # a close-all is settling; pause before re-fire
        self.resume_at: float = 0.0
        self.last_fired_at: datetime | None = None
        self.last_result: str | None = None


# After a fire, wait for positions to flatten AND this long before the account
# auto-close can fire again (prevents re-firing during the close lag).
_AUTOCLOSE_COOLDOWN_S = 5.0

_autoclose = _AutoCloseState()
# Default: arm the account auto-close at the configured target (0 disables).
_autoclose.target_usd = get_settings().orderflow_autoclose_default_usd or None
_autoclose.auto_arm = _autoclose.target_usd is not None

# The live collector ingest socket + a lock, so commands (close_all /
# close_symbol) can be sent safely from either the ingest receive task or a REST
# handler task without two coroutines writing the same socket concurrently.
_collector_ws: WebSocket | None = None
_collector_send_lock = asyncio.Lock()


async def _send_to_collector(payload: dict[str, Any]) -> bool:
    """Send one command to the connected collector. False if none connected."""
    async with _collector_send_lock:
        if _collector_ws is None:
            return False
        await _collector_ws.send_json(payload)
        return True


def _open_profit() -> float:
    """Summed floating P&L across all open positions in every tracked symbol."""
    return sum(p.profit for ps in _positions_store.values() for p in ps)


def _book_bid_ask(snapshot: OrderFlowSnapshot) -> tuple[float, float] | None:
    """Top-of-book (bid, ask) from a snapshot, or None if absent."""
    book = snapshot.book
    if book is None or not book.bids or not book.asks:
        return None
    return book.bids[0].price, book.asks[0].price


def _book_mid(snapshot: OrderFlowSnapshot) -> float | None:
    ba = _book_bid_ask(snapshot)
    return (ba[0] + ba[1]) / 2.0 if ba else None


def _range_per_bar(snapshot: OrderFlowSnapshot) -> float:
    """Recent per-bar range (ATR proxy) used to size the grid; 0 if unknown."""
    return snapshot.live_activity.range_per_bar if snapshot.live_activity else 0.0


def _symbol_side(positions: list[Position]) -> Direction | None:
    """The net side held on a symbol — shared with the flow-signal use case so
    the signal and the bot always judge the same side (see `held_side`)."""
    return held_side(positions)


def _autoclose_status() -> AutoCloseStatus:
    return AutoCloseStatus(
        enabled=_autoclose.enabled,
        armed=_autoclose.armed,
        target_usd=_autoclose.target_usd,
        open_profit=_open_profit(),
        last_fired_at=_autoclose.last_fired_at,
        last_result=_autoclose.last_result,
    )


async def _maybe_autoclose() -> None:
    """Fire the account profit target if reached. In auto-arm mode it re-arms
    after firing (stays on across fires/refreshes); otherwise it's one-shot."""
    if not _autoclose.armed:
        return
    now = time.monotonic()
    # Settling a previous fire: wait until flat AND past the cooldown before it
    # can fire again, so it doesn't re-fire on the same still-open profit.
    if _autoclose.cooling:
        open_count = sum(len(ps) for ps in _positions_store.values())
        if open_count == 0 and now >= _autoclose.resume_at:
            _autoclose.cooling = False
        return
    profit = _open_profit()
    if not should_autoclose(profit, _autoclose.target_usd, _autoclose.armed):
        return
    _autoclose.last_fired_at = datetime.now(timezone.utc)
    target = _autoclose.target_usd
    if not _autoclose.enabled:
        # Armed but the collector can't execute (reconnected without the flag).
        _autoclose.armed = False
        _autoclose.last_result = "abortado: collector sem allow_auto_close"
        logger.warning("Auto-close target hit but collector cannot execute")
        return
    if _autoclose.auto_arm:
        # Stay armed; just cool down while the close settles, then re-arm.
        _autoclose.cooling = True
        _autoclose.resume_at = now + _AUTOCLOSE_COOLDOWN_S
        _autoclose.last_result = f"meta +{profit:.2f} — fechou, re-armado (alvo {target:.2f})"
    else:
        _autoclose.armed = False  # one-shot
        _autoclose.last_result = f"disparo: P&L {profit:.2f} >= alvo {target:.2f} — fechando tudo"
    logger.info("Auto-close firing: %s", _autoclose.last_result)
    await _send_to_collector({"type": "close_all", "reason": _autoclose.last_result})


# --- explosion-scalper bot (opens AND closes; demo only) ---------------------


# Execution policy constants (thin gate, re-arm cooldown, profit lock) live in
# `use_cases/scalper.py` so the tape replay runs the exact same policy.
_THIN_RATIO = THIN_RATIO
_REARM_COOLDOWN_S = REARM_COOLDOWN_S
_BOT_LOCK_MIN_USD = LOCK_MIN_USD
_BOT_LOCK_GIVEBACK = LOCK_GIVEBACK


class _BotState:
    """Mutable scalper-bot state. `enabled` mirrors the collector's
    auto-trade-on-demo capability (from hello); arming is refused otherwise.

    24h mode: on a +profit_target cycle it banks the win into `realized`, flattens
    and re-arms; it hard-stops for the day only when the *session* P&L
    (realized + floating) hits −loss_stop. `flattening` suppresses entries/exits
    while a close-all is settling so a win isn't double-counted."""

    def __init__(self) -> None:
        self.enabled: bool = False  # collector allow_auto_trade AND demo account
        self.armed: bool = False
        self.rearm: bool = True  # cycle after each win (24h) vs one-shot
        self.profit_target: float = 35.0  # bank + re-arm at +this (floating)
        self.loss_stop: float = 200.0  # hard stop for the day at −this (session)
        self.max_per_symbol: int = 6
        self.cooldown_s: float = 2.0  # min gap between adds on a symbol (paces scale-in)
        # Per-symbol hard USD stop (0 = off; see scalper.SYMBOL_STOP_USD).
        self.symbol_stop_usd: float = SYMBOL_STOP_USD
        self.lots: dict[AssetSymbol, float] = {}  # per-symbol size; defaults below
        self.cooldown_until: dict[AssetSymbol, float] = {}
        self.realized: float = 0.0  # banked P&L this session
        self.peak: dict[AssetSymbol, float] = {}  # peak unrealized P&L per symbol (profit lock)
        # Per-symbol grid region while in a trade: {"side", "breach"} — `breach`
        # is the price beyond which the whole grid failed (→ cut/reverse).
        self.grid: dict[AssetSymbol, dict[str, Any]] = {}
        self.flattening: bool = False  # an account close-all is settling; pause
        self.resume_at: float = 0.0  # monotonic time to resume after flatten
        # Per-symbol stop-and-reverse in progress → captured P&L to bank once that
        # symbol is confirmed flat (banked on flat, not at issue, to avoid double
        # counting against the still-open floating during the close lag).
        self.closing: dict[AssetSymbol, float] = {}
        self.last_result: str | None = None


# Default per-symbol sizes: the broker minimum, 0.01 lots on every symbol. The
# ActivTrades account is small (about $1k), so the minimum is the whole setup —
# on the Sep26 index CFDs 0.01 is $0.20 a point on USTEC, $0.50 on USA500, $0.05
# on US30 and EUR 0.25 on GER40. A symbol missing from this map is skipped by
# the bot entirely. The per-symbol inputs in the bot panel overwrite them at
# runtime.
_DEFAULT_LOTS: dict[AssetSymbol, float] = {
    AssetSymbol.USTEC: 0.01,
    AssetSymbol.SPX: 0.01,
    AssetSymbol.GOLD: 0.01,
    AssetSymbol.US30: 0.01,
    AssetSymbol.GER40: 0.01,
    AssetSymbol.EURUSD: 0.01,
}

_bot = _BotState()
_bot.lots = dict(_DEFAULT_LOTS)

# Trade-history store for the bot's own executions. Set at app startup (see
# api/app.py); None in tests/headless unless injected. Recording is best-effort
# — a DB hiccup must never break the live bot or the ingest stream.
_bot_trade_repo: Any = None


def set_bot_trade_repo(repo: Any) -> None:
    global _bot_trade_repo
    _bot_trade_repo = repo


async def _record_bot_trade(**fields: Any) -> None:
    """Persist one bot execution event. Guarded so storage problems are logged
    and ignored rather than propagated into the trading loop."""
    if _bot_trade_repo is None:
        return
    try:
        await _bot_trade_repo.record(**fields)
    except Exception:  # never let persistence break the bot
        logger.exception("Failed to record bot trade: %r", fields)


def _bot_status() -> BotStatus:
    return BotStatus(
        enabled=_bot.enabled,
        armed=_bot.armed,
        profit_target=_bot.profit_target,
        loss_stop=_bot.loss_stop,
        symbol_stop_usd=_bot.symbol_stop_usd,
        open_profit=_open_profit(),
        realized=_bot.realized,
        open_count=sum(len(ps) for ps in _positions_store.values()),
        last_result=_bot.last_result,
        lots={sym.value: lot for sym, lot in _bot.lots.items()},
    )


async def _run_bot(snaps: dict[AssetSymbol, OrderFlowSnapshot]) -> None:
    """One bot tick: settle a pending close, then account-wide exit, then
    explosion entries on the symbols that just updated. Called from the ingest
    loop after each message with the SAME stamped snapshots that were just
    broadcast to the UI — the bot's enter/reverse decisions read the
    `flow_signal` on those snapshots, so it acts on exactly what the user sees.
    """
    if not _bot.armed:
        return

    now = time.monotonic()
    open_count = sum(len(ps) for ps in _positions_store.values())

    # Settling a previous close-all: do nothing until flat AND past the cooldown,
    # so a banked win isn't re-counted and we don't re-enter the spent move.
    if _bot.flattening:
        if open_count == 0 and now >= _bot.resume_at:
            _bot.flattening = False
        return

    floating = _open_profit()
    session = _bot.realized + floating

    # Hard daily stop on session drawdown (realized + floating) — stops for good.
    if session <= -_bot.loss_stop:
        _bot.armed = False
        _bot.realized = session
        _bot.last_result = f"stop diário (sessão {session:.2f}) — fechou tudo e parou"
        logger.warning("Bot daily stop: %s", _bot.last_result)
        # History is recorded from the collector's result (real broker P&L).
        await _send_to_collector({"type": "close_all", "reason": "stop", "origin": "bot"})
        return

    # Profit target on this cycle's floating → bank it, then re-arm (24h) or stop.
    if floating >= _bot.profit_target:
        _bot.realized += floating
        if _bot.rearm:
            _bot.flattening = True
            _bot.resume_at = now + _REARM_COOLDOWN_S
            _bot.last_result = f"meta +{floating:.2f} (sessão {_bot.realized:.2f}) — re-armando"
        else:
            _bot.armed = False
            _bot.last_result = f"meta +{floating:.2f} (sessão {_bot.realized:.2f}) — parou"
        logger.info("Bot exit: %s", _bot.last_result)
        await _send_to_collector({"type": "close_all", "reason": "target", "origin": "bot"})
        return

    # Entries / reversals: only the symbols whose flow just moved.
    for symbol, snap in snaps.items():
        if symbol not in _bot.lots:
            continue
        positions = _positions_store.get(symbol, [])
        signal = snap.flow_signal  # the exact signal just broadcast to the UI

        # Settling a per-symbol close (reverse or profit-lock): wait until flat,
        # then bank the captured P&L and reset its peak. Re-entry on a later tick.
        if symbol in _bot.closing:
            if not positions:
                _bot.realized += _bot.closing.pop(symbol)
                _bot.peak.pop(symbol, None)
                _bot.grid.pop(symbol, None)
            continue

        if not positions and now >= _bot.cooldown_until.get(symbol, 0.0):
            # Genuinely flat (not just waiting on a just-sent entry to fill — the
            # entry cooldown covers that lag, so we don't wipe a fresh grid region
            # before its market order reports back). Forget the old peak + grid.
            _bot.peak.pop(symbol, None)
            _bot.grid.pop(symbol, None)

        current_side = _symbol_side(positions)
        sym_pnl = sum(p.profit for p in positions)

        # Per-symbol hard stop (checked before the lock/reverse reads): caps the
        # DOLLAR damage of one scaled-in symbol without waiting for the price to
        # break the grid region or the whole session to hit the daily stop.
        if current_side is not None and symbol_stopped(sym_pnl, _bot.symbol_stop_usd):
            _bot.closing[symbol] = sym_pnl
            _bot.cooldown_until[symbol] = now + _bot.cooldown_s
            _bot.last_result = (
                f"stop {symbol.value}: {sym_pnl:.2f} <= -{_bot.symbol_stop_usd:.2f} — cortando"
            )
            logger.info("Bot symbol stop: %s", _bot.last_result)
            await _send_to_collector(
                {
                    "type": "close_symbol",
                    "symbol": symbol.value,
                    "origin": "bot",
                    "reason": "stop",
                    "side": current_side,
                }
            )
            continue

        # Trailing profit lock: track the peak unrealized P&L; if a meaningful
        # gain gives back too much while still positive, bank it now instead of
        # letting it round-trip to breakeven.
        if current_side is not None:
            peak = max(_bot.peak.get(symbol, 0.0), sym_pnl)
            _bot.peak[symbol] = peak
            if peak >= _BOT_LOCK_MIN_USD and 0 < sym_pnl <= peak * (1.0 - _BOT_LOCK_GIVEBACK):
                _bot.closing[symbol] = sym_pnl
                _bot.cooldown_until[symbol] = now + _bot.cooldown_s
                _bot.last_result = (
                    f"lock {symbol.value}: +{sym_pnl:.2f} (pico {peak:.2f}) — realizando"
                )
                logger.info("Bot profit-lock: %s", _bot.last_result)
                await _send_to_collector(
                    {
                        "type": "close_symbol",
                        "symbol": symbol.value,
                        "origin": "bot",
                        "reason": "lock",
                        "side": current_side,
                    }
                )
                continue

        # Hybrid reverse: the grid catches pullbacks, but if price breaks past the
        # whole region (deepest level + buffer) the trade has failed → close (the
        # collector also cancels the unfilled limits) and let it re-enter/flip.
        # Fall back to the flow-signal reverse if no grid region is recorded.
        # NOTE: manual positions (not opened by the bot) have NO grid region, so
        # they always take the signal's stop-and-reverse fallback — the same
        # deliberately twitchy tape read shown on the UI (12 prints, 0.20 lean
        # against, basis="reversal"). An armed bot manages manual trades too;
        # this is how it cuts a short on a buy-side tape burst even while price
        # drifts the trade's way. See backend/README.md.
        if current_side is not None:
            grid = _bot.grid.get(symbol)
            mid = _book_mid(snap)
            broke = (
                grid is not None
                and mid is not None
                and region_broken(mid, current_side, grid["breach"])
            )
            if broke or (grid is None and signal_says_reverse(signal)):
                _bot.closing[symbol] = sym_pnl
                _bot.cooldown_until[symbol] = now + _bot.cooldown_s
                why = "região rompida" if broke else "fluxo virou contra"
                _bot.last_result = f"reversão {symbol.value}: {why} — fechando"
                logger.info("Bot reverse: %s", _bot.last_result)
                await _send_to_collector(
                    {
                        "type": "close_symbol",
                        "symbol": symbol.value,
                        "origin": "bot",
                        "reason": "reverse",
                        "side": current_side,
                    }
                )
                continue

        # Entry: only when FLAT and with no grid region pending (the grid does the
        # scaling — no same-price market adds). A fresh explosion opens 1 market
        # order + an ATR-spaced grid of limits below (buy) / above (sell).
        if positions or symbol in _bot.grid:
            continue
        liq = _liquidity_store.get(symbol)
        liquidity_ok = liq is None or liq.ratio >= _THIN_RATIO
        # The entry direction comes from the broadcast flow signal (flat →
        # explosion-only by construction) — same object the UI is showing.
        direction = signal_entry_direction(signal)
        cooldown_ok = now >= _bot.cooldown_until.get(symbol, 0.0)
        if not should_open(
            direction=direction,
            open_on_symbol=0,
            max_per_symbol=_bot.max_per_symbol,
            cooldown_ok=cooldown_ok,
            daily_halted=False,
            liquidity_ok=liquidity_ok,
        ):
            continue
        assert direction is not None  # should_open guarantees it
        ba = _book_bid_ask(snap)
        rpb = _range_per_bar(snap)
        if ba is None or rpb <= 0:
            continue  # need a quote + range to size the grid
        bid, ask = ba
        entry = ask if direction == "buy" else bid
        levels = grid_levels(entry, direction, rpb)
        breach = grid_breach_price(entry, direction, rpb)
        _bot.grid[symbol] = {"side": direction, "breach": breach}
        _bot.cooldown_until[symbol] = now + _bot.cooldown_s
        _bot.last_result = (
            f"abriu {direction} {symbol.value} {_bot.lots[symbol]}lt + grade {len(levels)} níveis"
        )
        logger.info("Bot entry: %s", _bot.last_result)
        await _send_to_collector(
            {
                "type": "open",
                "symbol": symbol.value,
                "side": direction,
                "lots": _bot.lots[symbol],
                "grid": levels,
            }
        )


async def _handle_message(msg: dict[str, Any]) -> set[AssetSymbol]:
    """Feed one ingest message into the aggregator. Returns symbols touched."""
    global _current_source, _current_account, _account_pnl, _auto_trade_enabled
    global _mark_last_result
    mtype = msg.get("type")

    if mtype == "hello":
        # Identifies which MT5 terminal (FTMO, ActivTrades, …) is feeding flow,
        # and whether that collector is allowed to execute auto-close orders.
        src = msg.get("source")
        if isinstance(src, str) and src:
            _current_source = src
            logger.info("Order-flow source set: %s", src)
        acct = msg.get("account")
        if isinstance(acct, int):
            _current_account = acct
            logger.info("Order-flow account set: %s", acct)
        _autoclose.enabled = bool(msg.get("auto_close_enabled", False))
        if not _autoclose.enabled and _autoclose.armed:
            # Lost execution capability (reconnect without the flag) → disarm.
            _autoclose.armed = False
            _autoclose.last_result = "desarmado: collector reconectou sem allow_auto_close"
        elif (
            _autoclose.enabled
            and _autoclose.auto_arm
            and not _autoclose.armed
            and _autoclose.target_usd
        ):
            # Default-on: arm the account auto-close as soon as the collector can
            # execute, so it survives backend restarts / UI refreshes.
            _autoclose.armed = True
            _autoclose.cooling = False
            _autoclose.last_result = f"auto-armado: alvo {_autoclose.target_usd:.2f}"
            logger.info("Auto-close auto-armed at %.2f", _autoclose.target_usd)
        # Scalper bot needs to BOTH open and close, on a demo account: it requires
        # auto-trade AND auto-close capability (else it could open and never be
        # able to exit — the −loss_stop guard would be unable to close).
        # Raw open capability, used by the manual chart-marker (no demo gate).
        _auto_trade_enabled = bool(msg.get("auto_trade_enabled", False))
        # Demo-only by default; `auto_trade_live_ok` is the collector's explicit
        # opt-in to open REAL positions on a non-demo account (e.g. FTMO).
        _bot.enabled = (
            _auto_trade_enabled
            and bool(msg.get("auto_close_enabled", False))
            and (
                bool(msg.get("account_is_demo", False))
                or bool(msg.get("auto_trade_live_ok", False))
            )
        )
        if not _bot.enabled and _bot.armed:
            _bot.armed = False
            _bot.last_result = "desarmado: collector sem auto_trade+auto_close/conta demo"
        logger.info("Execution capability — auto_close=%s bot=%s", _autoclose.enabled, _bot.enabled)
        return set()

    if mtype == "account_pnl":
        # Realized P&L (day/week/month) from the broker's deal history — all
        # closed trades, manual and bot. Latest push wins; served over REST.
        _account_pnl = AccountPnl(
            day=float(msg.get("day", 0.0) or 0.0),
            week=float(msg.get("week", 0.0) or 0.0),
            month=float(msg.get("month", 0.0) or 0.0),
            currency=msg.get("currency") if isinstance(msg.get("currency"), str) else None,
            asof=datetime.now(timezone.utc),
        )
        # The same message carries the live account balance/equity (added to the
        # collector's account read). Record a live equity sample when present —
        # the store coalesces idle samples so a flat account doesn't grow.
        bal, eq = msg.get("balance"), msg.get("equity")
        if bal is not None and eq is not None:
            _balance_history.record_equity(
                balance=float(bal),
                equity=float(eq),
                currency=_account_pnl.currency,
                ts=_account_pnl.asof or datetime.now(timezone.utc),
            )
        return set()

    if mtype == "balance_history":
        # Per-trade balance curve reconstructed by the collector from the broker
        # deal history (manual + bot). Replaces the current steps wholesale.
        steps: list[BalanceStep] = []
        for raw in msg.get("points", ()):
            ts = _parse_dt(raw.get("ts"))
            if ts is None:
                continue
            try:
                steps.append(
                    BalanceStep(
                        ts=ts,
                        balance=float(raw["balance"]),
                        pnl=float(raw.get("pnl", 0.0) or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        _balance_history.set_steps(
            steps,
            balance=float(msg.get("balance", 0.0) or 0.0),
            currency=msg.get("currency") if isinstance(msg.get("currency"), str) else None,
        )
        return set()

    if mtype == "trade_history":
        # Closed round-trip trades rebuilt by the collector from the broker deal
        # history (manual AND bot). The store merges by MT5 position id, so
        # re-pushes are idempotent and trades that age out of the collector's
        # window are kept. Feeds the Performance tab over REST.
        parsed: list[ClosedTrade] = []
        for raw in msg.get("trades", ()):
            try:
                parsed.append(ClosedTrade.model_validate(raw))
            except Exception:  # one malformed trade must not drop the push
                continue
        # Same push carries the account's deposits/withdrawals, so the report
        # can keep money paid in apart from money made.
        flows: list[CashFlow] = []
        for raw in msg.get("cash_flows", ()):
            try:
                flows.append(CashFlow.model_validate(raw))
            except Exception:
                continue
        trade_history.merge(
            parsed,
            cash_flows=flows,
            balance=float(msg["balance"]) if msg.get("balance") is not None else None,
            currency=msg.get("currency") if isinstance(msg.get("currency"), str) else None,
            asof=msg.get("asof") if isinstance(msg.get("asof"), str) else None,
        )
        logger.info(
            "Trade history push: %d closed trades, %d balance operations",
            len(parsed),
            len(flows),
        )
        return set()

    if mtype == "autoclose_result":
        # The collector reporting the outcome of a close it executed, with the
        # broker's REAL realized `pnl`. Record bot-originated closes in history
        # (faithful to the broker); manual closes are not recorded.
        ok = bool(msg.get("ok"))
        closed = msg.get("closed")
        err = msg.get("error") or msg.get("errors")
        _autoclose.last_result = (
            f"fechado: {closed} posição(ões)" if ok else f"falha ao fechar: {err}"
        )
        logger.info("Auto-close result: ok=%s closed=%s err=%s", ok, closed, err)
        if msg.get("origin") == "bot":
            await _record_bot_trade(
                kind="close",
                symbol=str(msg.get("symbol", "ALL")),
                side=msg.get("side"),
                pnl=float(msg["pnl"]) if msg.get("pnl") is not None else None,
                reason=msg.get("reason"),
            )
        return set()

    if mtype == "open_result":
        ok = bool(msg.get("ok"))
        sym = msg.get("symbol")
        if ok:
            _bot.last_result = f"abriu {msg.get('side')} {sym} (ticket {msg.get('ticket')})"
            # Persist the executed open (bot trades only — there is no manual open).
            await _record_bot_trade(
                kind="open",
                symbol=str(sym),
                side=msg.get("side"),
                lots=float(msg["lots"]) if msg.get("lots") is not None else None,
                ticket=int(msg["ticket"]) if msg.get("ticket") is not None else None,
                price=float(msg["price"]) if msg.get("price") is not None else None,
            )
        else:
            _bot.last_result = f"falha ao abrir {sym}: {msg.get('error')}"
        logger.info("Bot open result: %s", _bot.last_result)
        return set()

    if mtype == "mark_result":
        # Outcome of a chart-marker pending order the collector placed. Not a
        # bot trade — just surfaced in logs / status, never recorded.
        ok = bool(msg.get("ok"))
        sym = msg.get("symbol")
        if ok:
            replaced = msg.get("replaced") or 0
            _mark_last_result = (
                f"marcador {msg.get('side')} {sym} @{msg.get('price')} "
                f"({msg.get('lots')} lt, ticket {msg.get('ticket')}"
                + (f", substituiu {replaced}" if replaced else "")
                + ")"
            )
        else:
            _mark_last_result = f"falha ao marcar {sym}: {msg.get('error')}"
        logger.info("Mark result: %s", _mark_last_result)
        return set()

    if mtype == "breakeven_result":
        # The collector reporting the outcome of a breakeven SL modification.
        ok = bool(msg.get("ok"))
        moved = msg.get("moved")
        skipped = msg.get("skipped")
        err = msg.get("error") or msg.get("errors")
        if ok:
            _autoclose.last_result = f"breakeven: {moved} movida(s)" + (
                f", {skipped} sem lucro ainda" if skipped else ""
            )
        else:
            _autoclose.last_result = f"falha no breakeven: {err}"
        logger.info("Breakeven result: ok=%s moved=%s skipped=%s err=%s", ok, moved, skipped, err)
        return set()

    symbol = _parse_symbol(msg.get("symbol"))
    if symbol is None or not aggregator.tracks(symbol):
        return set()

    if mtype == "book":
        aggregator.ingest_book(_parse_book(msg, symbol))
        return {symbol}
    if mtype == "trade":
        aggregator.ingest_trade(_parse_trade(msg, symbol))
        return {symbol}
    if mtype == "trades":
        trades = [_parse_trade({**raw, "symbol": symbol}, symbol) for raw in msg.get("trades", ())]
        if trades:
            aggregator.ingest_trades(symbol, trades)
        return {symbol}
    if mtype == "liquidity":
        # Session-liquidity reading. Stored for the day-outlook gate AND stamped
        # onto the symbol's snapshot, so the flow column can show it above the
        # pressure bar. Touch the symbol so the snapshot is re-broadcast now.
        _liquidity_store[symbol] = _parse_liquidity(msg, symbol)
        return {symbol}
    if mtype == "candles":
        # M5 bars for the symbol, merged into the stored history. A malformed
        # bar raises and the ingest loop skips the whole message (so a bad push
        # can never half-write the history).
        _merge_candles(
            symbol,
            [
                IntradayBar(
                    timestamp=_parse_dt(raw["ts"]),
                    open=float(raw["o"]),
                    high=float(raw["h"]),
                    low=float(raw["l"]),
                    close=float(raw["c"]),
                    volume=float(raw.get("v", 0.0) or 0.0),
                )
                for raw in msg.get("bars", ())
            ],
        )
        return set()
    if mtype == "positions":
        # Open positions for this symbol (read-only). An empty list is a valid,
        # meaningful update — it means "now flat", so a closed trade clears.
        _positions_store[symbol] = [
            _parse_position(raw, symbol) for raw in msg.get("positions", ())
        ]
        return {symbol}
    logger.debug("Ignoring unknown order-flow message type: %r", mtype)
    return set()


def _stamp_snapshot(snapshot: "OrderFlowSnapshot") -> "OrderFlowSnapshot":
    """Return the snapshot with the broker source + latest liquidity baked in,
    plus THE per-symbol flow signal (entry/exit decision support). The stamped
    snapshot is what browsers receive AND what the armed bot reads — one
    computation, one truth."""
    update: dict[str, Any] = {}
    if _current_source is not None:
        update["source"] = _current_source
    if _current_account is not None:
        update["account"] = _current_account
    liq = _liquidity_store.get(snapshot.symbol)
    if liq is not None:
        update["liquidity"] = liq
    positions = _positions_store.get(snapshot.symbol) or []
    if positions:
        update["positions"] = positions
        # Deterministic in-trade alerts from the current flow lean + positions.
        signals = assess_trade_signals(snapshot, positions)
        if signals:
            update["signals"] = signals
    # Always computed (an entry signal exists precisely when flat).
    update["flow_signal"] = compute_flow_signal(snapshot, positions)
    return snapshot.model_copy(update=update)


# --- ingest (collector → backend) -------------------------------------------


@router.websocket("/ws/ingest/orderflow")
async def ingest_ws(websocket: WebSocket) -> None:
    """Receive raw book/trade messages from the MT5 collector.

    Auth: ``?token=<ORDERFLOW_INGEST_TOKEN>``. Rejected when the feature is
    disabled, the token is unset, or the token does not match.
    """
    settings = get_settings()
    token = settings.orderflow_ingest_token
    presented = websocket.query_params.get("token", "")

    if not settings.orderflow_enabled or token is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("Order-flow ingest refused: feature disabled or token unset")
        return
    if presented != token.get_secret_value():
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("Order-flow ingest refused: bad token from %s", websocket.client)
        return

    global _collector_ws
    await websocket.accept()
    _collector_ws = websocket  # latest collector wins; used to send commands back
    logger.info("Order-flow collector connected: %s", websocket.client)
    try:
        while True:
            msg = await websocket.receive_json()
            # Record the raw message BEFORE parsing: the tape must contain the
            # session exactly as received, and the recorder never raises.
            if _tape_recorder is not None:
                _tape_recorder.record(msg)
            try:
                touched = await _handle_message(msg)
            except (KeyError, ValueError, TypeError):
                # A single malformed message must not drop the whole stream —
                # log and keep consuming so the collector stays connected.
                logger.warning("Skipping malformed order-flow message: %r", msg)
                continue
            # Stamp once per touched symbol; the SAME objects are broadcast to
            # the UI and handed to the bot, so signal shown == signal acted on.
            stamped = {s: _stamp_snapshot(aggregator.snapshot(s)) for s in touched}
            for snapshot in stamped.values():
                await orderflow_broadcaster.publish(snapshot)
            # Evaluate the profit-target auto-close after each message (cheap; the
            # P&L only moves on position updates). Disarms itself on fire.
            await _maybe_autoclose()
            # Run the scalper bot (entries on the touched symbols + account exits).
            await _run_bot(stamped)
    except WebSocketDisconnect:
        logger.info("Order-flow collector disconnected: %s", websocket.client)
    except Exception:
        logger.exception("Order-flow ingest handler crashed for %s", websocket.client)
        try:
            await websocket.close(code=1011)
        except Exception:  # pragma: no cover - already closed
            pass
    finally:
        # Only clear if we're still the active socket (a newer collector may have
        # replaced us). Stops commands being sent to a dead connection.
        if _collector_ws is websocket:
            _collector_ws = None


# --- subscribe (backend → browser) ------------------------------------------


@router.websocket("/ws/orderflow")
async def orderflow_ws(websocket: WebSocket) -> None:
    """Stream per-symbol OrderFlowSnapshot JSON to the browser."""
    await websocket.accept()
    logger.info("Order-flow viewer connected: %s", websocket.client)
    try:
        async for snapshot in orderflow_broadcaster.subscribe():
            await websocket.send_json(snapshot.model_dump(mode="json"))
    except WebSocketDisconnect:
        logger.info("Order-flow viewer disconnected: %s", websocket.client)
    except Exception:
        logger.exception("Order-flow viewer handler crashed for %s", websocket.client)
        try:
            await websocket.close(code=1011)
        except Exception:  # pragma: no cover - already closed
            pass


# --- REST snapshot -----------------------------------------------------------


@router.get("/api/orderflow", response_model=list[OrderFlowSnapshot], tags=["orderflow"])
async def get_orderflow() -> list[OrderFlowSnapshot]:
    """Latest order-flow snapshot per symbol (prefers the live broadcaster
    cache, falls back to the aggregator's current state)."""
    cached = orderflow_broadcaster.latest_all()
    if cached:
        return cached
    return [_stamp_snapshot(s) for s in aggregator.all_snapshots()]


@router.get("/api/orderflow/pnl", response_model=AccountPnl, tags=["orderflow"])
async def get_account_pnl() -> AccountPnl:
    """Realized account P&L over the calendar day / week / month (all closed
    trades — manual and bot). All-zero until the collector's first push."""
    return _account_pnl or AccountPnl()


@router.get(
    "/api/orderflow/balance/history",
    response_model=AccountBalanceHistory,
    tags=["orderflow"],
)
async def get_balance_history() -> AccountBalanceHistory:
    """Balance chart data: a per-trade balance step curve (from the broker deal
    history, backfilled for the month) + forward-only live equity samples.
    Empty until the collector's first push."""
    steps, equity = _balance_history.snapshot()
    last_eq: EquityPoint | None = equity[-1] if equity else None
    asof = last_eq.ts if last_eq else (steps[-1].ts if steps else None)
    return AccountBalanceHistory(
        balance_steps=steps,
        equity_points=equity,
        balance=_balance_history.balance,
        equity=last_eq.equity if last_eq else _balance_history.balance,
        currency=_balance_history.currency,
        asof=asof,
    )


# --- auto-close (whole-account profit target) --------------------------------


class AutoCloseRequest(BaseModel):
    """Arm/disarm the whole-account profit-target auto-close from the UI."""

    armed: bool
    target_usd: float | None = None


@router.get(
    "/api/orderflow/candles",
    response_model=dict[AssetSymbol, list[IntradayBar]],
    tags=["orderflow"],
)
async def get_candles(limit: int = _CHART_CANDLES) -> dict[AssetSymbol, list[IntradayBar]]:
    """Latest M5 candles per symbol pushed by the collector (newest last; the
    final bar is still forming). Empty until the collector's first push.

    `limit` caps how many bars each symbol returns — the chart only draws the
    recent ones, so the deep history kept for the band scenario stays server
    side instead of being polled over the wire every few seconds.
    """
    count = max(1, min(limit, _MAX_CANDLES))
    return {symbol: bars[-count:] for symbol, bars in _candles_store.items()}


@router.get(
    "/api/orderflow/bands",
    response_model=dict[AssetSymbol, BandScenario],
    tags=["orderflow"],
)
async def get_band_scenarios() -> dict[AssetSymbol, BandScenario]:
    """Where price usually went from its current spot inside the Bollinger
    band, measured on each symbol's own stored bars.

    Symbols without enough history (or without enough past bars at the same
    spot in the band) are simply absent — a thin sample must show nothing
    rather than a number nobody should trade on.
    """
    scenarios: dict[AssetSymbol, BandScenario] = {}
    for symbol, bars in _candles_store.items():
        scenario = project_band_path(symbol, bars)
        if scenario is not None:
            scenarios[symbol] = scenario
    return scenarios


@router.get("/api/orderflow/autoclose", response_model=AutoCloseStatus, tags=["orderflow"])
async def get_autoclose() -> AutoCloseStatus:
    return _autoclose_status()


@router.post("/api/orderflow/autoclose", response_model=AutoCloseStatus, tags=["orderflow"])
async def set_autoclose(body: AutoCloseRequest) -> AutoCloseStatus:
    """Arm or disarm the auto-close.

    Arming requires (a) the collector to permit execution (`allow_auto_close`)
    and (b) a positive target. Disarming always succeeds — it's the kill switch.
    """
    if body.armed:
        if not _autoclose.enabled:
            raise HTTPException(
                status_code=409,
                detail="O collector não habilitou auto-close (allow_auto_close=true no config.json).",
            )
        if body.target_usd is None or body.target_usd <= 0:
            raise HTTPException(
                status_code=422, detail="target_usd deve ser um valor positivo para armar."
            )
    _autoclose.armed = body.armed
    _autoclose.target_usd = body.target_usd
    # A manual arm keeps it auto-arming (persist at this target); a manual disarm
    # turns auto-arming off so it stays off until the user arms again.
    _autoclose.auto_arm = body.armed
    _autoclose.cooling = False
    _autoclose.last_result = (
        f"armado: alvo {body.target_usd:.2f}" if body.armed else "desarmado pelo usuário"
    )
    logger.info("Auto-close %s (target=%s)", "ARMED" if body.armed else "disarmed", body.target_usd)
    return _autoclose_status()


@router.post("/api/orderflow/close/{symbol}", tags=["orderflow"])
async def close_symbol(symbol: str) -> dict[str, Any]:
    """Manually close ALL open positions for one symbol (the per-asset button).

    Same execution gate as auto-close: requires the collector to permit it
    (`allow_auto_close`). Fires immediately; the close result comes back async
    from the collector and lands in the auto-close status `last_result`.
    """
    sym = _parse_symbol(symbol)
    if sym is None or not aggregator.tracks(sym):
        raise HTTPException(status_code=404, detail=f"Símbolo não rastreado: {symbol}")
    if not _autoclose.enabled:
        raise HTTPException(
            status_code=409,
            detail="O collector não habilitou execução (allow_auto_close=true no config.json).",
        )
    sent = await _send_to_collector({"type": "close_symbol", "symbol": sym.value})
    if not sent:
        raise HTTPException(status_code=503, detail="Collector não conectado.")
    logger.info("Manual close requested for %s", sym.value)
    return {"ok": True, "detail": f"Fechamento de {sym.value} enviado ao collector."}


@router.post("/api/orderflow/breakeven/{symbol}", tags=["orderflow"])
async def breakeven_symbol(symbol: str) -> dict[str, Any]:
    """Move every open position on one symbol to breakeven (SL → entry price).

    Same execution gate as the per-asset close: requires the collector to permit
    it (`allow_auto_close`, since it's an order_send). Fires immediately; the
    result comes back async from the collector and lands in the status
    `last_result`. Positions not yet in profit are skipped by the collector."""
    sym = _parse_symbol(symbol)
    if sym is None or not aggregator.tracks(sym):
        raise HTTPException(status_code=404, detail=f"Símbolo não rastreado: {symbol}")
    if not _autoclose.enabled:
        raise HTTPException(
            status_code=409,
            detail="O collector não habilitou execução (allow_auto_close=true no config.json).",
        )
    sent = await _send_to_collector({"type": "breakeven_symbol", "symbol": sym.value})
    if not sent:
        raise HTTPException(status_code=503, detail="Collector não conectado.")
    logger.info("Breakeven requested for %s", sym.value)
    return {"ok": True, "detail": f"Breakeven de {sym.value} enviado ao collector."}


# --- chart marker (min-lot pending order to mark an entry zone) --------------


class MarkRequest(BaseModel):
    """Place a min-lot pending order to draw an entry line on the MT5 chart.

    Give the target as EITHER `price` (an absolute price on the collector's
    broker feed) OR `offset` (signed price-points from the current market —
    the safe form, since it never mixes the yfinance level scale with the FTMO
    tape scale). LIMIT vs STOP is picked by the collector so it's always valid.
    """

    side: Literal["buy", "sell"]
    price: float | None = None
    offset: float | None = None
    lots: float = 0.01


@router.post("/api/orderflow/mark/{symbol}", tags=["orderflow"])
async def mark_symbol(symbol: str, body: MarkRequest) -> dict[str, Any]:
    """Drop a 0.01-lot pending order at a recommended entry zone so it shows as
    a line on the chart. Requires the collector's open capability
    (`allow_auto_trade`). The order can fill (it's real, min-lot); it is a
    marker, not a pure annotation — the MT5 Python API can't draw objects.
    The place result comes back async from the collector."""
    sym = _parse_symbol(symbol)
    if sym is None or not aggregator.tracks(sym):
        raise HTTPException(status_code=404, detail=f"Símbolo não rastreado: {symbol}")
    if body.price is None and body.offset is None:
        raise HTTPException(
            status_code=422, detail="Informe 'price' (absoluto) ou 'offset' (pontos do mercado)."
        )
    if body.lots <= 0:
        raise HTTPException(status_code=422, detail="lots deve ser > 0.")
    if not _auto_trade_enabled:
        raise HTTPException(
            status_code=409,
            detail="O collector não habilitou allow_auto_trade=true no config.json.",
        )
    sent = await _send_to_collector(
        {
            "type": "mark",
            "symbol": sym.value,
            "side": body.side,
            "price": body.price,
            "offset": body.offset,
            "lots": body.lots,
        }
    )
    if not sent:
        raise HTTPException(status_code=503, detail="Collector não conectado.")
    logger.info(
        "Chart marker requested: %s %s price=%s offset=%s lots=%s",
        body.side,
        sym.value,
        body.price,
        body.offset,
        body.lots,
    )
    return {"ok": True, "detail": f"Marcador {body.side} de {sym.value} enviado ao collector."}


# --- scalper bot (opens AND closes; demo only) -------------------------------


class BotRequest(BaseModel):
    """Arm/disarm the explosion-scalper bot."""

    armed: bool
    profit_target: float | None = None
    loss_stop: float | None = None
    lots: dict[str, float] | None = None  # per-symbol trade size (e.g. {"USTEC": 0.01})
    symbol_stop_usd: float | None = None  # per-symbol hard USD stop (0 = off)


@router.get("/api/orderflow/bot", response_model=BotStatus, tags=["orderflow"])
async def get_bot() -> BotStatus:
    return _bot_status()


@router.post("/api/orderflow/bot", response_model=BotStatus, tags=["orderflow"])
async def set_bot(body: BotRequest) -> BotStatus:
    """Arm or disarm the scalper. Arming requires the collector to permit
    auto-trade on a DEMO account, and positive profit target / loss stop.
    Disarming always succeeds (kill switch); it does NOT close open positions —
    use the per-asset button or auto-close for that."""
    # Per-symbol lot sizes can be updated on any request (armed or not) so the
    # user can dial size down to the 0.01 minimum before/while testing.
    if body.lots is not None:
        for key, lot in body.lots.items():
            try:
                sym = AssetSymbol(key)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"símbolo inválido: {key}") from exc
            if not lot > 0:
                raise HTTPException(status_code=422, detail=f"lote de {key} deve ser > 0.")
            _bot.lots[sym] = float(lot)

    if body.armed:
        if not _bot.enabled:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Bot indisponível: o collector precisa de allow_auto_trade=true E "
                    "allow_auto_close=true (pra poder fechar) E conta DEMO."
                ),
            )
        if body.profit_target is not None:
            if body.profit_target <= 0:
                raise HTTPException(status_code=422, detail="profit_target deve ser > 0.")
            _bot.profit_target = body.profit_target
        if body.loss_stop is not None:
            if body.loss_stop <= 0:
                raise HTTPException(status_code=422, detail="loss_stop deve ser > 0.")
            _bot.loss_stop = body.loss_stop
        if body.symbol_stop_usd is not None:
            if body.symbol_stop_usd < 0:
                raise HTTPException(status_code=422, detail="symbol_stop_usd deve ser >= 0.")
            _bot.symbol_stop_usd = body.symbol_stop_usd
        # Fresh session: clear cooldowns, banked P&L and any settling state.
        _bot.cooldown_until.clear()
        _bot.closing.clear()
        _bot.peak.clear()
        _bot.grid.clear()
        _bot.realized = 0.0
        _bot.flattening = False
        _bot.resume_at = 0.0
    _bot.armed = body.armed
    _bot.last_result = (
        f"bot ARMADO (meta +{_bot.profit_target:.0f} / stop −{_bot.loss_stop:.0f})"
        if body.armed
        else "bot desarmado pelo usuário"
    )
    logger.info("Scalper bot %s", "ARMED" if body.armed else "disarmed")
    return _bot_status()


@router.get("/api/orderflow/bot/trades", response_model=list[BotTrade], tags=["orderflow"])
async def get_bot_trades(limit: int = 200) -> list[BotTrade]:
    """Recent bot executions (newest first) for performance analysis. Only bot
    trades are recorded — never manual ones."""
    if _bot_trade_repo is None:
        return []
    limit = max(1, min(limit, 1000))
    return await _bot_trade_repo.list_recent(limit)
