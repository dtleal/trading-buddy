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

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.orderflow_broadcaster import orderflow_broadcaster
from core.enums import AssetSymbol
from core.models import OrderBookLevel, OrderBookSnapshot, OrderFlowSnapshot, TapeTrade
from settings import get_settings
from use_cases.aggregate_orderflow import OrderFlowAggregator

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


async def _handle_message(msg: dict[str, Any]) -> set[AssetSymbol]:
    """Feed one ingest message into the aggregator. Returns symbols touched."""
    mtype = msg.get("type")
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
        for raw in msg.get("trades", ()):
            aggregator.ingest_trade(_parse_trade({**raw, "symbol": symbol}, symbol))
        return {symbol}
    logger.debug("Ignoring unknown order-flow message type: %r", mtype)
    return set()


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

    await websocket.accept()
    logger.info("Order-flow collector connected: %s", websocket.client)
    try:
        while True:
            msg = await websocket.receive_json()
            touched = await _handle_message(msg)
            for symbol in touched:
                await orderflow_broadcaster.publish(aggregator.snapshot(symbol))
    except WebSocketDisconnect:
        logger.info("Order-flow collector disconnected: %s", websocket.client)
    except Exception:
        logger.exception("Order-flow ingest handler crashed for %s", websocket.client)
        try:
            await websocket.close(code=1011)
        except Exception:  # pragma: no cover - already closed
            pass


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
    return aggregator.all_snapshots()
