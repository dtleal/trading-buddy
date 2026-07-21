"""Parsers for the collector's wire format (ingest WebSocket messages).

Extracted from the ingest route so the scalper replay/backtest reads a recorded
tape (see `adapters/tape_recorder.py`) through EXACTLY the same parsing as the
live stream — one wire format, one parser, no drift between live and replay.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.enums import AssetSymbol
from core.models import (
    OrderBookLevel,
    OrderBookSnapshot,
    Position,
    SessionLiquidity,
    TapeTrade,
)


def parse_dt(value: Any) -> datetime:
    """Parse an ISO-8601 string (with optional trailing Z) to aware UTC."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_symbol(value: Any) -> AssetSymbol | None:
    try:
        return AssetSymbol(str(value).upper())
    except ValueError:
        return None


def parse_levels(raw: Any) -> list[OrderBookLevel]:
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


def parse_book(msg: dict[str, Any], symbol: AssetSymbol) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        symbol=symbol,
        asof=parse_dt(msg.get("asof") or msg.get("at")),
        bids=parse_levels(msg.get("bids")),
        asks=parse_levels(msg.get("asks")),
    )


def parse_liquidity(msg: dict[str, Any], symbol: AssetSymbol) -> SessionLiquidity:
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
        asof=parse_dt(msg.get("asof") or msg.get("at")),
        realized_volume=realized,
        baseline_volume=baseline,
        ratio=ratio,
        sample_days=int(msg.get("sample_days", 0)),
        realized_range=float(realized_range) if realized_range is not None else None,
        baseline_range=float(baseline_range) if baseline_range is not None else None,
        range_ratio=float(range_ratio) if range_ratio is not None else None,
    )


def nonzero_price(value: Any) -> float | None:
    """MT5 reports an unset SL/TP as 0.0; treat that as 'no level'."""
    if value is None:
        return None
    price = float(value)
    return price if price != 0.0 else None


def parse_position(raw: dict[str, Any], symbol: AssetSymbol) -> Position:
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
        sl=nonzero_price(raw.get("sl")),
        tp=nonzero_price(raw.get("tp")),
        seconds_open=float(raw.get("seconds_open", 0.0)),
    )


def parse_trade(msg: dict[str, Any], symbol: AssetSymbol) -> TapeTrade:
    side = str(msg.get("side", "unknown")).lower()
    if side not in ("buy", "sell", "unknown"):
        side = "unknown"
    return TapeTrade(
        symbol=symbol,
        at=parse_dt(msg.get("at") or msg.get("asof")),
        price=float(msg["price"]),
        volume=float(msg.get("volume", 0.0)),
        side=side,  # type: ignore[arg-type]
    )


__all__ = [
    "parse_dt",
    "parse_symbol",
    "parse_levels",
    "parse_book",
    "parse_liquidity",
    "parse_position",
    "parse_trade",
    "nonzero_price",
]
