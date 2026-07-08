"""Unit tests for the collector's pure tick-classification helpers.

The MT5 collector itself only runs on Windows, but its aggressor-side logic
(`_tick_side`, `_classify_quote_tick`), the synthesized-print volume rule and
the tape-mode "usable print" predicate are pure functions — so we import the
module directly (its MetaTrader5 import degrades to None off-Windows) and pin
the classification rules down here, where the backend suite runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

_COLLECTOR_DIR = Path(__file__).resolve().parents[3] / "collector"
sys.path.insert(0, str(_COLLECTOR_DIR))

from mt5_orderflow_collector import (  # noqa: E402
    _TICK_FLAG_BUY,
    _TICK_FLAG_LAST,
    _TICK_FLAG_SELL,
    _classify_quote_tick,
    _quote_tick_volume,
    _tick_side,
    _usable_trade_tick,
)

BID, ASK = 99.0, 101.0


# --- _tick_side (real-tape path) -------------------------------------------


def test_tick_side_prefers_broker_flags() -> None:
    # Flags are authoritative even when the price says otherwise.
    assert _tick_side(_TICK_FLAG_BUY, BID, BID, ASK) == "buy"
    assert _tick_side(_TICK_FLAG_SELL, ASK, BID, ASK) == "sell"


def test_tick_side_infers_from_last_vs_quote() -> None:
    assert _tick_side(0, ASK, BID, ASK) == "buy"  # at/above the ask = lift
    assert _tick_side(0, BID, BID, ASK) == "sell"  # at/below the bid = hit
    assert _tick_side(0, 100.0, BID, ASK) == "unknown"  # inside the spread


# --- _classify_quote_tick (synthesized path) --------------------------------


def test_quote_classify_flags_win_over_everything() -> None:
    # Even on a mid downtick with last at the bid, a BUY flag decides.
    assert _classify_quote_tick(_TICK_FLAG_BUY, BID, BID, ASK, 101.0, 100.0) == "buy"
    assert _classify_quote_tick(_TICK_FLAG_SELL, ASK, BID, ASK, 99.0, 100.0) == "sell"


def test_quote_classify_fresh_last_vs_quote_beats_mid_tick() -> None:
    # A FRESH trade print (TICK_FLAG_LAST) at the ask on a mid DOWNTICK → still a
    # buy (quote rule > tick test). At the bid on a mid UPTICK → still a sell.
    assert _classify_quote_tick(_TICK_FLAG_LAST, ASK, BID, ASK, 101.0, 100.0) == "buy"
    assert _classify_quote_tick(_TICK_FLAG_LAST, BID, BID, ASK, 99.0, 100.0) == "sell"


def test_quote_classify_stale_last_is_ignored_uses_mid_tick() -> None:
    # `last` at the bid but WITHOUT TICK_FLAG_LAST is carried forward from an
    # older deal — it must NOT force a sell. On a mid uptick the tick test wins,
    # so this classifies buy (guards the stale-last bias on quote-only feeds).
    assert _classify_quote_tick(0, BID, BID, ASK, 99.0, 100.0) == "buy"
    assert _classify_quote_tick(0, ASK, BID, ASK, 101.0, 100.0) == "sell"


def test_quote_classify_last_inside_spread_falls_to_mid_tick() -> None:
    assert _classify_quote_tick(0, 100.0, BID, ASK, 99.5, 100.0) == "buy"  # uptick
    assert _classify_quote_tick(0, 100.0, BID, ASK, 100.5, 100.0) == "sell"  # downtick
    # Inside the spread with an unchanged mid → no directional information.
    assert _classify_quote_tick(0, 100.0, BID, ASK, 100.0, 100.0) is None


def test_quote_classify_no_last_uses_pure_mid_tick_test() -> None:
    assert _classify_quote_tick(0, 0.0, BID, ASK, 99.5, 100.0) == "buy"
    assert _classify_quote_tick(0, 0.0, BID, ASK, 100.5, 100.0) == "sell"
    assert _classify_quote_tick(0, 0.0, BID, ASK, 100.0, 100.0) is None  # unchanged
    assert _classify_quote_tick(0, 0.0, BID, ASK, None, 100.0) is None  # first tick


# --- _quote_tick_volume ------------------------------------------------------


def test_quote_tick_volume_prefers_real_then_int_then_count_proxy() -> None:
    assert _quote_tick_volume(2.5, 3.0) == 2.5  # volume_real wins
    assert _quote_tick_volume(0.0, 3.0) == 3.0  # else integer volume
    assert _quote_tick_volume(0.0, 0.0) == 1.0  # else the tick-count proxy


# --- _usable_trade_tick (tape auto-detect) -----------------------------------


def test_usable_trade_tick_requires_price_and_flags_or_size() -> None:
    assert _usable_trade_tick(0, 0.0, 5.0, 5.0) is False  # no trade price
    assert _usable_trade_tick(0, 100.0, 0.0, 0.0) is False  # husk: no flags/size
    assert _usable_trade_tick(_TICK_FLAG_BUY, 100.0, 0.0, 0.0) is True
    assert _usable_trade_tick(_TICK_FLAG_SELL, 100.0, 0.0, 0.0) is True
    assert _usable_trade_tick(0, 100.0, 1.5, 0.0) is True  # sized print
    assert _usable_trade_tick(0, 100.0, 0.0, 2.0) is True
