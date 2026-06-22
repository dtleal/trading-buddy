"""Unit tests for the explosion-scalper entry engine (pure, boundary-focused).

This logic decides whether to OPEN real trades, so the burst detection and the
entry gate are pinned down at their thresholds and on every refusal reason.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.enums import AssetSymbol
from core.models import LiveActivity, OrderFlowSnapshot, TapeTrade
from use_cases.scalper import (
    EXPANSION_MULT,
    MIN_PRINTS,
    STRONG_FRACTION,
    detect_explosion,
    should_open,
)

_AT = datetime(2026, 6, 9, 14, 0, 0, tzinfo=timezone.utc)


def _snap(
    buys: int,
    sells: int,
    *,
    window_range: float = 10.0,
    range_per_bar: float | None = 2.0,
) -> OrderFlowSnapshot:
    sides = ["buy"] * buys + ["sell"] * sells
    trades = [
        TapeTrade(
            symbol=AssetSymbol.USTEC,
            at=_AT,
            # Alternate lo/hi so the window's price travel == window_range.
            price=100.0 if i % 2 == 0 else 100.0 + window_range,
            volume=1.0,
            side=s,  # type: ignore[arg-type]
        )
        for i, s in enumerate(sides)
    ]
    live = (
        None
        if range_per_bar is None
        else LiveActivity(
            range_per_bar=range_per_bar, volume_per_bar=10.0, interval_seconds=60, sampled_bars=5
        )
    )
    return OrderFlowSnapshot(
        symbol=AssetSymbol.USTEC, asof=_AT, recent_trades=trades, live_activity=live
    )


def test_no_baseline_no_explosion() -> None:
    assert detect_explosion(_snap(20, 3, range_per_bar=None)) is None
    assert detect_explosion(_snap(20, 3, range_per_bar=0.0)) is None


def test_too_few_prints() -> None:
    assert detect_explosion(_snap(5, 5)) is None  # 10 < MIN_PRINTS


def test_strong_buy_burst_with_expansion() -> None:
    assert detect_explosion(_snap(20, 3, window_range=10.0, range_per_bar=2.0)) == "buy"


def test_strong_sell_burst_with_expansion() -> None:
    assert detect_explosion(_snap(3, 20, window_range=10.0, range_per_bar=2.0)) == "sell"


def test_strong_direction_without_expansion_is_none() -> None:
    # Directional but not moving fast enough → not a burst.
    assert detect_explosion(_snap(20, 3, window_range=3.0, range_per_bar=2.0)) is None


def test_expansion_without_direction_is_none() -> None:
    assert detect_explosion(_snap(12, 12, window_range=10.0, range_per_bar=2.0)) is None


def test_fraction_boundary_is_inclusive() -> None:
    assert STRONG_FRACTION == 0.70  # guard the table
    # 14/20 = 0.70 exactly → fires.
    assert detect_explosion(_snap(14, 6, window_range=10.0, range_per_bar=2.0)) == "buy"


def test_expansion_threshold() -> None:
    assert EXPANSION_MULT == 1.8 and MIN_PRINTS == 12  # guard the table
    # Just above 1.8 * range_per_bar (=3.6) fires; just below does not.
    assert detect_explosion(_snap(20, 3, window_range=3.7, range_per_bar=2.0)) == "buy"
    assert detect_explosion(_snap(20, 3, window_range=3.5, range_per_bar=2.0)) is None


def test_should_open_gates() -> None:
    base = dict(open_on_symbol=0, max_per_symbol=6, cooldown_ok=True, daily_halted=False)
    assert should_open(direction="buy", **base) is True
    assert should_open(direction=None, **base) is False
    assert should_open(direction="buy", **{**base, "daily_halted": True}) is False
    assert should_open(direction="buy", **{**base, "cooldown_ok": False}) is False
    # At the per-symbol cap (>=) → no more adds.
    assert should_open(direction="buy", **{**base, "open_on_symbol": 6}) is False
    assert should_open(direction="buy", **{**base, "open_on_symbol": 5}) is True
