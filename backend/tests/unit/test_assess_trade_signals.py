"""Unit tests for the in-trade signal rules (pure, table-driven).

Covers both rules at their threshold boundaries, mutual exclusion, the
min-sample gate, and the divide-by-zero guards.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import AssetSymbol
from core.models import OrderFlowSnapshot, Position, TapeTrade
from use_cases.assess_trade_signals import (
    AGAINST,
    AGAINST_STRONG,
    MIN_PRINTS,
    STALL,
    assess_trade_signals,
)

_AT = datetime(2026, 6, 9, 14, 0, 0, tzinfo=timezone.utc)


def _trades(buys: int, sells: int, unknown: int = 0) -> list[TapeTrade]:
    out: list[TapeTrade] = []
    for side, n in (("buy", buys), ("sell", sells), ("unknown", unknown)):
        for _ in range(n):
            out.append(
                TapeTrade(symbol=AssetSymbol.USTEC, at=_AT, price=100.0, volume=1.0, side=side)  # type: ignore[arg-type]
            )
    return out


def _snapshot(buys: int, sells: int, unknown: int = 0) -> OrderFlowSnapshot:
    return OrderFlowSnapshot(
        symbol=AssetSymbol.USTEC, asof=_AT, recent_trades=_trades(buys, sells, unknown)
    )


def _pos(side: str, *, ticket: int = 1, profit: float = 0.0) -> Position:
    return Position(
        symbol=AssetSymbol.USTEC,
        ticket=ticket,
        side=side,  # type: ignore[arg-type]
        volume=1.0,
        price_open=100.0,
        price_current=100.0,
        profit=profit,
        seconds_open=5.0,
    )


def test_no_positions_yields_nothing() -> None:
    assert assess_trade_signals(_snapshot(5, 5), []) == []


def test_too_few_prints_stays_silent() -> None:
    # Fewer than MIN_PRINTS directional prints → no judgement, even if lopsided.
    snap = _snapshot(0, MIN_PRINTS - 1)
    assert assess_trade_signals(snap, [_pos("buy")]) == []


def test_only_unknown_prints_no_divide_by_zero() -> None:
    snap = _snapshot(0, 0, unknown=20)
    assert assess_trade_signals(snap, [_pos("buy", profit=50.0)]) == []


def test_long_with_strong_sell_pressure_is_urgent_against() -> None:
    # 2 buys / 8 sells → buy_pct 0.2 → lean -0.30 = AGAINST_STRONG boundary.
    sig = assess_trade_signals(_snapshot(2, 8), [_pos("buy")])
    assert len(sig) == 1
    assert sig[0].code == "pressure_against"
    assert sig[0].severity == "urgent"
    assert sig[0].stance == "against"
    assert "vendedores" in sig[0].message.lower()


def test_long_with_moderate_sell_pressure_is_warn_against() -> None:
    # 3 buys / 7 sells → buy_pct 0.3 → lean -0.20, between AGAINST and STRONG.
    sig = assess_trade_signals(_snapshot(3, 7), [_pos("buy")])
    assert len(sig) == 1
    assert sig[0].code == "pressure_against"
    assert sig[0].severity == "warn"


def test_short_with_strong_buy_pressure_is_against() -> None:
    # 8 buys / 2 sells → buy_pct 0.8 → for a short, lean = 0.5 - 0.8 = -0.30.
    sig = assess_trade_signals(_snapshot(8, 2), [_pos("sell")])
    assert len(sig) == 1
    assert sig[0].code == "pressure_against"
    assert sig[0].severity == "urgent"
    assert "compradores" in sig[0].message.lower()


def test_favourable_flow_yields_no_signal() -> None:
    # Long with buyers in control and in profit → momentum still favours you.
    assert assess_trade_signals(_snapshot(8, 2), [_pos("buy", profit=40.0)]) == []


def test_profit_with_stalled_momentum_suggests_take_profit() -> None:
    # 5/5 → buy_pct 0.5 → lean 0.0 (≤ STALL) and in profit → take profit.
    sig = assess_trade_signals(_snapshot(5, 5), [_pos("buy", profit=25.0)])
    assert len(sig) == 1
    assert sig[0].code == "take_profit"
    assert sig[0].severity == "warn"
    assert sig[0].stance == "caution"


def test_stalled_momentum_without_profit_is_silent() -> None:
    # Same neutral lean but NOT in profit → no take-profit nudge.
    assert assess_trade_signals(_snapshot(5, 5), [_pos("buy", profit=0.0)]) == []
    assert assess_trade_signals(_snapshot(5, 5), [_pos("buy", profit=-10.0)]) == []


def test_against_preempts_take_profit_when_in_profit() -> None:
    # In profit AND flow strongly against → the louder "against" wins, no double.
    sig = assess_trade_signals(_snapshot(2, 8), [_pos("buy", profit=30.0)])
    assert len(sig) == 1
    assert sig[0].code == "pressure_against"


def test_against_boundary_is_inclusive() -> None:
    # lean exactly -AGAINST should fire (≤). 35/65 over 20 prints → lean -0.15.
    assert AGAINST == 0.15 and STALL == 0.05 and AGAINST_STRONG == 0.30  # guard the table
    sig = assess_trade_signals(_snapshot(7, 13), [_pos("buy")])
    assert sig and sig[0].code == "pressure_against" and sig[0].severity == "warn"


def test_pressure_is_volume_weighted_not_print_counted() -> None:
    """With a real tape the lean weighs SIZE: 8 small buys vs 4 big sells is
    seller control even though buy PRINTS outnumber sell prints 2:1."""
    trades = [
        TapeTrade(symbol=AssetSymbol.USTEC, at=_AT, price=100.0, volume=0.1, side="buy")
        for _ in range(8)
    ] + [
        TapeTrade(symbol=AssetSymbol.USTEC, at=_AT, price=100.0, volume=2.0, side="sell")
        for _ in range(4)
    ]
    snap = OrderFlowSnapshot(symbol=AssetSymbol.USTEC, asof=_AT, recent_trades=trades)
    # buy 0.8 / total 8.8 → buy_pct ≈ 0.091 → lean ≈ -0.41 for a long → urgent.
    sig = assess_trade_signals(snap, [_pos("buy")])
    assert len(sig) == 1
    assert sig[0].code == "pressure_against"
    assert sig[0].severity == "urgent"


def test_min_prints_gate_counts_prints_not_volume() -> None:
    """The sample gate is a PRINT count: a few huge prints must not unlock a
    judgement just because their summed volume is large."""
    trades = [
        TapeTrade(symbol=AssetSymbol.USTEC, at=_AT, price=100.0, volume=500.0, side="sell")
        for _ in range(MIN_PRINTS - 1)
    ]
    snap = OrderFlowSnapshot(symbol=AssetSymbol.USTEC, asof=_AT, recent_trades=trades)
    assert assess_trade_signals(snap, [_pos("buy")]) == []


def test_multiple_positions_each_judged_independently() -> None:
    # 2 buys / 8 sells: a long is against; a short is favoured (silent).
    snap = _snapshot(2, 8)
    sig = assess_trade_signals(snap, [_pos("buy", ticket=1), _pos("sell", ticket=2)])
    assert len(sig) == 1
    assert sig[0].ticket == 1 and sig[0].code == "pressure_against"
