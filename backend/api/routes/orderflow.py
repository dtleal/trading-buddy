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
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from api.orderflow_broadcaster import orderflow_broadcaster
from core.enums import AssetSymbol
from core.models import (
    AutoCloseStatus,
    BotStatus,
    BotTrade,
    OrderBookLevel,
    OrderBookSnapshot,
    OrderFlowSnapshot,
    Position,
    SessionLiquidity,
    TapeTrade,
)
from settings import get_settings
from use_cases.aggregate_orderflow import OrderFlowAggregator
from use_cases.assess_trade_signals import assess_trade_signals
from use_cases.autoclose import should_autoclose
from use_cases.scalper import Direction, decide_entry, should_open, should_reverse

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

# Latest per-symbol session-liquidity reading pushed by the collector. Lives in
# the same process as the tick loop (API + loop share a process), so the
# day-outlook assessor reads it directly — no DB / cache round-trip needed.
_liquidity_store: dict[AssetSymbol, SessionLiquidity] = {}

# Latest open positions per symbol pushed by the collector (read-only mirror of
# MT5). Lives in the same process as the ingest loop, like `_liquidity_store`,
# and is stamped onto each symbol's snapshot. An explicit empty list means the
# collector reported the symbol is flat (so a closed trade clears from the UI).
_positions_store: dict[AssetSymbol, list[Position]] = {}


def latest_liquidity() -> dict[AssetSymbol, SessionLiquidity]:
    """Snapshot of the most recent MT5 liquidity reading per symbol.

    Read by `RunDashboardTickUseCase` to feed the day-outlook gate. Returns a
    shallow copy so the caller can iterate without racing the ingest handler.
    """
    return dict(_liquidity_store)


# --- wire-format parsing -----------------------------------------------------


def _parse_dt(value: Any) -> datetime:
    """Parse an ISO-8601 string (with optional trailing Z) to aware UTC."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_symbol(value: Any) -> AssetSymbol | None:
    try:
        return AssetSymbol(str(value).upper())
    except ValueError:
        return None


def _parse_levels(raw: Any) -> list[OrderBookLevel]:
    levels: list[OrderBookLevel] = []
    for item in raw or ():
        # accept [price, volume] pairs or {"price":..,"volume":..}
        price: Any
        volume: Any
        if isinstance(item, dict):
            price, volume = item["price"], item["volume"]
        else:
            price, volume = item[0], item[1]
        levels.append(OrderBookLevel(price=float(price), volume=float(volume)))
    return levels


def _parse_book(msg: dict[str, Any], symbol: AssetSymbol) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol=symbol,
        asof=_parse_dt(msg.get("asof") or msg.get("at")),
        bids=_parse_levels(msg.get("bids")),
        asks=_parse_levels(msg.get("asks")),
    )


def _parse_liquidity(msg: dict[str, Any], symbol: AssetSymbol) -> SessionLiquidity:
    realized = float(msg["realized_volume"])
    baseline = float(msg["baseline_volume"])
    # Prefer the collector's own ratio, but recompute defensively when absent.
    ratio = msg.get("ratio")
    ratio = float(ratio) if ratio is not None else (realized / baseline if baseline > 0 else 0.0)
    realized_range = msg.get("realized_range")
    baseline_range = msg.get("baseline_range")
    range_ratio = msg.get("range_ratio")
    if range_ratio is None and realized_range is not None and baseline_range:
        range_ratio = float(realized_range) / float(baseline_range)
    return SessionLiquidity(
        symbol=symbol,
        asof=_parse_dt(msg.get("asof") or msg.get("at")),
        realized_volume=realized,
        baseline_volume=baseline,
        ratio=ratio,
        sample_days=int(msg.get("sample_days", 0)),
        realized_range=float(realized_range) if realized_range is not None else None,
        baseline_range=float(baseline_range) if baseline_range is not None else None,
        range_ratio=float(range_ratio) if range_ratio is not None else None,
    )


def _nonzero_price(value: Any) -> float | None:
    """MT5 reports an unset SL/TP as 0.0; treat that as 'no level'."""
    if value is None:
        return None
    price = float(value)
    return price if price != 0.0 else None


def _parse_position(raw: dict[str, Any], symbol: AssetSymbol) -> Position:
    side = str(raw.get("side", "")).lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"position side must be buy/sell, got {side!r}")
    return Position(
        symbol=symbol,
        ticket=int(raw["ticket"]),
        side=side,  # type: ignore[arg-type]
        volume=float(raw["volume"]),
        price_open=float(raw["price_open"]),
        price_current=float(raw["price_current"]),
        profit=float(raw["profit"]),
        sl=_nonzero_price(raw.get("sl")),
        tp=_nonzero_price(raw.get("tp")),
        seconds_open=float(raw.get("seconds_open", 0.0)),
    )


def _parse_trade(msg: dict[str, Any], symbol: AssetSymbol) -> TapeTrade:
    side = str(msg.get("side", "unknown")).lower()
    if side not in ("buy", "sell", "unknown"):
        side = "unknown"
    return TapeTrade(
        symbol=symbol,
        at=_parse_dt(msg.get("at") or msg.get("asof")),
        price=float(msg["price"]),
        volume=float(msg.get("volume", 0.0)),
        side=side,  # type: ignore[arg-type]
    )


# Connection-level state set by the collector's `hello` message. One collector
# per backend process today, so a module-level slot is enough; if we ever
# multiplex collectors per-symbol we'd promote this into the aggregator.
_current_source: str | None = None


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
        self.last_fired_at: datetime | None = None
        self.last_result: str | None = None


_autoclose = _AutoCloseState()

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


def _symbol_side(positions: list[Position]) -> Direction | None:
    """The net side held on a symbol: 'buy'/'sell', or None when flat or tied
    (a tie should not happen with direction-consistent entries; treated as
    'don't add' for safety)."""
    buys = sum(1 for p in positions if p.side == "buy")
    sells = sum(1 for p in positions if p.side == "sell")
    if buys > sells:
        return "buy"
    if sells > buys:
        return "sell"
    return None


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
    """Fire the profit target if reached: disarm (one-shot) and tell the
    collector to close everything."""
    if not _autoclose.armed:
        return
    profit = _open_profit()
    if not should_autoclose(profit, _autoclose.target_usd, _autoclose.armed):
        return
    _autoclose.armed = False  # one-shot, regardless of what happens next
    _autoclose.last_fired_at = datetime.now(timezone.utc)
    target = _autoclose.target_usd
    if not _autoclose.enabled:
        # Armed but the collector can't execute (reconnected without the flag).
        _autoclose.last_result = "abortado: collector sem allow_auto_close"
        logger.warning("Auto-close target hit but collector cannot execute")
        return
    _autoclose.last_result = f"disparo: P&L {profit:.2f} >= alvo {target:.2f} — fechando tudo"
    logger.info("Auto-close firing: %s", _autoclose.last_result)
    await _send_to_collector({"type": "close_all", "reason": _autoclose.last_result})


# --- explosion-scalper bot (opens AND closes; demo only) ---------------------


# Session is thin (skip entries) when realized participation is below this share
# of the same-time-of-day baseline — matches the dashboard's "thin" threshold.
_THIN_RATIO = 0.75
# After banking a win we wait for positions to flatten AND this long before the
# bot opens again, so it doesn't immediately re-enter the exhausted move.
_REARM_COOLDOWN_S = 5.0


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
        self.profit_target: float = 350.0  # bank + re-arm at +this (floating)
        self.loss_stop: float = 900.0  # hard stop for the day at −this (session)
        self.max_per_symbol: int = 6
        self.cooldown_s: float = 2.0  # min gap between adds on a symbol (paces scale-in)
        self.lots: dict[AssetSymbol, float] = {}  # per-symbol size; defaults below
        self.cooldown_until: dict[AssetSymbol, float] = {}
        self.realized: float = 0.0  # banked P&L this session
        self.flattening: bool = False  # an account close-all is settling; pause
        self.resume_at: float = 0.0  # monotonic time to resume after flatten
        # Per-symbol stop-and-reverse in progress → captured P&L to bank once that
        # symbol is confirmed flat (banked on flat, not at issue, to avoid double
        # counting against the still-open floating during the close lag).
        self.closing: dict[AssetSymbol, float] = {}
        self.last_result: str | None = None


# Default per-symbol sizes (Diego's: index 2.0 lots, gold 0.12).
_DEFAULT_LOTS: dict[AssetSymbol, float] = {
    AssetSymbol.USTEC: 2.0,
    AssetSymbol.SPX: 2.0,
    AssetSymbol.GOLD: 0.12,
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
        open_profit=_open_profit(),
        realized=_bot.realized,
        open_count=sum(len(ps) for ps in _positions_store.values()),
        last_result=_bot.last_result,
    )


async def _run_bot(touched: set[AssetSymbol]) -> None:
    """One bot tick: settle a pending close, then account-wide exit, then
    explosion entries on the symbols that just updated. Called from the ingest
    loop after each message."""
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
        await _record_bot_trade(kind="close", symbol="ALL", pnl=floating, reason="stop")
        await _send_to_collector({"type": "close_all", "reason": _bot.last_result})
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
        await _record_bot_trade(kind="close", symbol="ALL", pnl=floating, reason="target")
        await _send_to_collector({"type": "close_all", "reason": _bot.last_result})
        return

    # Entries / reversals: only the symbols whose flow just moved.
    for symbol in touched:
        if symbol not in _bot.lots:
            continue
        positions = _positions_store.get(symbol, [])

        # Settling a stop-and-reverse close on this symbol: wait until it's flat,
        # then bank the captured P&L. Re-entry happens on a later tick.
        if symbol in _bot.closing:
            if not positions:
                _bot.realized += _bot.closing.pop(symbol)
            continue

        snap = aggregator.snapshot(symbol)
        current_side = _symbol_side(positions)

        # Stop & reverse: flow flipped hard against the held side → close it now.
        # Banked on flat (above); re-entry into the new side comes via the normal
        # explosion path once flat + cooldown.
        if current_side is not None and should_reverse(snap, current_side):
            reverse_pnl = sum(p.profit for p in positions)
            _bot.closing[symbol] = reverse_pnl
            _bot.cooldown_until[symbol] = now + _bot.cooldown_s
            _bot.last_result = (
                f"reversão {symbol.value}: fluxo virou contra {current_side} — fechando"
            )
            logger.info("Bot reverse: %s", _bot.last_result)
            await _record_bot_trade(
                kind="close",
                symbol=symbol.value,
                side=current_side,
                pnl=reverse_pnl,
                reason="reverse",
            )
            await _send_to_collector({"type": "close_symbol", "symbol": symbol.value})
            continue

        liq = _liquidity_store.get(symbol)
        liquidity_ok = liq is None or liq.ratio >= _THIN_RATIO
        # Direction matching what we already hold (or an explosion when flat);
        # never the opposite side of an open position.
        direction = decide_entry(
            snap,
            current_side=current_side,
            open_on_symbol=len(positions),
        )
        cooldown_ok = now >= _bot.cooldown_until.get(symbol, 0.0)
        if should_open(
            direction=direction,
            open_on_symbol=len(positions),
            max_per_symbol=_bot.max_per_symbol,
            cooldown_ok=cooldown_ok,
            daily_halted=False,
            liquidity_ok=liquidity_ok,
        ):
            _bot.cooldown_until[symbol] = now + _bot.cooldown_s
            _bot.last_result = f"abriu {direction} {symbol.value} {_bot.lots[symbol]} lt"
            logger.info("Bot entry: %s", _bot.last_result)
            await _send_to_collector(
                {
                    "type": "open",
                    "symbol": symbol.value,
                    "side": direction,
                    "lots": _bot.lots[symbol],
                }
            )


async def _handle_message(msg: dict[str, Any]) -> set[AssetSymbol]:
    """Feed one ingest message into the aggregator. Returns symbols touched."""
    global _current_source
    mtype = msg.get("type")

    if mtype == "hello":
        # Identifies which MT5 terminal (FTMO, ActivTrades, …) is feeding flow,
        # and whether that collector is allowed to execute auto-close orders.
        src = msg.get("source")
        if isinstance(src, str) and src:
            _current_source = src
            logger.info("Order-flow source set: %s", src)
        _autoclose.enabled = bool(msg.get("auto_close_enabled", False))
        if not _autoclose.enabled and _autoclose.armed:
            # Lost execution capability (reconnect without the flag) → disarm.
            _autoclose.armed = False
            _autoclose.last_result = "desarmado: collector reconectou sem allow_auto_close"
        # Scalper bot needs auto-trade AND a demo account.
        _bot.enabled = bool(msg.get("auto_trade_enabled", False)) and bool(
            msg.get("account_is_demo", False)
        )
        if not _bot.enabled and _bot.armed:
            _bot.armed = False
            _bot.last_result = "desarmado: collector sem auto_trade/conta demo"
        logger.info("Execution capability — auto_close=%s bot=%s", _autoclose.enabled, _bot.enabled)
        return set()

    if mtype == "autoclose_result":
        # The collector reporting the outcome of a close_all it executed.
        ok = bool(msg.get("ok"))
        closed = msg.get("closed")
        err = msg.get("error") or msg.get("errors")
        _autoclose.last_result = (
            f"fechado: {closed} posição(ões)" if ok else f"falha ao fechar: {err}"
        )
        logger.info("Auto-close result: ok=%s closed=%s err=%s", ok, closed, err)
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
    """Return the snapshot with the broker source + latest liquidity baked in."""
    update: dict[str, Any] = {}
    if _current_source is not None:
        update["source"] = _current_source
    liq = _liquidity_store.get(snapshot.symbol)
    if liq is not None:
        update["liquidity"] = liq
    positions = _positions_store.get(snapshot.symbol)
    if positions:
        update["positions"] = positions
        # Deterministic in-trade alerts from the current flow lean + positions.
        signals = assess_trade_signals(snapshot, positions)
        if signals:
            update["signals"] = signals
    return snapshot.model_copy(update=update) if update else snapshot


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
            try:
                touched = await _handle_message(msg)
            except (KeyError, ValueError, TypeError):
                # A single malformed message must not drop the whole stream —
                # log and keep consuming so the collector stays connected.
                logger.warning("Skipping malformed order-flow message: %r", msg)
                continue
            for symbol in touched:
                await orderflow_broadcaster.publish(_stamp_snapshot(aggregator.snapshot(symbol)))
            # Evaluate the profit-target auto-close after each message (cheap; the
            # P&L only moves on position updates). Disarms itself on fire.
            await _maybe_autoclose()
            # Run the scalper bot (entries on the touched symbols + account exits).
            await _run_bot(touched)
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


# --- auto-close (whole-account profit target) --------------------------------


class AutoCloseRequest(BaseModel):
    """Arm/disarm the whole-account profit-target auto-close from the UI."""

    armed: bool
    target_usd: float | None = None


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


# --- scalper bot (opens AND closes; demo only) -------------------------------


class BotRequest(BaseModel):
    """Arm/disarm the explosion-scalper bot."""

    armed: bool
    profit_target: float | None = None
    loss_stop: float | None = None


@router.get("/api/orderflow/bot", response_model=BotStatus, tags=["orderflow"])
async def get_bot() -> BotStatus:
    return _bot_status()


@router.post("/api/orderflow/bot", response_model=BotStatus, tags=["orderflow"])
async def set_bot(body: BotRequest) -> BotStatus:
    """Arm or disarm the scalper. Arming requires the collector to permit
    auto-trade on a DEMO account, and positive profit target / loss stop.
    Disarming always succeeds (kill switch); it does NOT close open positions —
    use the per-asset button or auto-close for that."""
    if body.armed:
        if not _bot.enabled:
            raise HTTPException(
                status_code=409,
                detail="Bot indisponível: o collector precisa de allow_auto_trade=true E conta DEMO.",
            )
        if body.profit_target is not None:
            if body.profit_target <= 0:
                raise HTTPException(status_code=422, detail="profit_target deve ser > 0.")
            _bot.profit_target = body.profit_target
        if body.loss_stop is not None:
            if body.loss_stop <= 0:
                raise HTTPException(status_code=422, detail="loss_stop deve ser > 0.")
            _bot.loss_stop = body.loss_stop
        # Fresh session: clear cooldowns, banked P&L and any settling state.
        _bot.cooldown_until.clear()
        _bot.closing.clear()
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
