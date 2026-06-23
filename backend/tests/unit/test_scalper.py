"""Unit tests for the explosion-scalper entry engine (pure, boundary-focused).

This logic decides whether to OPEN real trades, so the burst detection and the
entry gate are pinned down at their thresholds and on every refusal reason.
"""

from __future__ import annotations

from datetime import datetime, timezone

from core.enums import AssetSymbol
from core.models import LiveActivity, OrderFlowSnapshot, TapeTrade
from use_cases.scalper import (
    ADD_LEAN,
    EXPANSION_MULT,
    MIN_PRINTS,
    REVERSE_LEAN,
    STRONG_FRACTION,
    decide_entry,
    detect_explosion,
    grid_breach_price,
    grid_levels,
    region_broken,
    should_open,
    should_reverse,
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


def test_decide_entry_flat_requires_explosion() -> None:
    # Flat: a burst opens; a calm/weak window does not.
    assert decide_entry(_snap(20, 3), current_side=None, open_on_symbol=0) == "buy"
    assert decide_entry(_snap(12, 12), current_side=None, open_on_symbol=0) is None


def test_decide_entry_adds_in_held_direction_without_explosion() -> None:
    # Holding sells, flow still leans sell (no range expansion needed) → add sell.
    snap = _snap(3, 17, window_range=2.0, range_per_bar=10.0)  # no expansion
    assert detect_explosion(snap) is None  # would NOT re-trigger as a burst
    assert decide_entry(snap, current_side="sell", open_on_symbol=3) == "sell"


def test_decide_entry_never_opposite_side() -> None:
    # Holding buys but flow flipped to sell → do NOT open a sell (no hedge).
    snap = _snap(3, 17)  # strongly sell
    assert decide_entry(snap, current_side="buy", open_on_symbol=2) is None


def test_decide_entry_stops_adding_when_lean_fades() -> None:
    assert ADD_LEAN == 0.10  # guard the table
    # Holding buys, flow back to ~neutral (lean < ADD_LEAN) → no add.
    assert decide_entry(_snap(11, 9), current_side="buy", open_on_symbol=2) is None


def test_decide_entry_ambiguous_hold_does_not_add() -> None:
    assert decide_entry(_snap(20, 3), current_side=None, open_on_symbol=4) is None


def test_should_reverse_on_strong_opposite_flow() -> None:
    assert REVERSE_LEAN == 0.20  # guard the table
    # Holding buys, flow flipped hard to sell (against = 0.35) → reverse.
    assert should_reverse(_snap(3, 17), "buy") is True
    # Holding sells, flow flipped hard to buy → reverse.
    assert should_reverse(_snap(17, 3), "sell") is True


def test_should_not_reverse_when_flow_still_favors_or_weak() -> None:
    # Flow still favours the held side → no reverse.
    assert should_reverse(_snap(17, 3), "buy") is False
    # Only mildly against (against = 0.05 < REVERSE_LEAN) → no reverse (anti-whipsaw).
    assert should_reverse(_snap(9, 11), "buy") is False
    # Too few prints → no reverse.
    assert should_reverse(_snap(2, 3), "buy") is False


def test_grid_levels_below_for_buy_above_for_sell() -> None:
    # range_per_bar 10, step_frac 0.5 → step 5 → 3 levels.
    assert grid_levels(100.0, "buy", 10.0) == [95.0, 90.0, 85.0]
    assert grid_levels(100.0, "sell", 10.0) == [105.0, 110.0, 115.0]
    assert grid_levels(100.0, "buy", 0.0) == []  # no range → no grid


def test_grid_breach_and_region_broken() -> None:
    # buy: deepest level 85 (3*5), breach buffer 0.5*5=2.5 → breach at 82.5.
    bp = grid_breach_price(100.0, "buy", 10.0)
    assert bp == 82.5
    assert region_broken(82.4, "buy", bp) is True
    assert region_broken(83.0, "buy", bp) is False
    # sell mirror: breach at 117.5.
    bps = grid_breach_price(100.0, "sell", 10.0)
    assert bps == 117.5
    assert region_broken(117.6, "sell", bps) is True
    assert region_broken(117.0, "sell", bps) is False


def test_should_open_gates() -> None:
    base = dict(open_on_symbol=0, max_per_symbol=6, cooldown_ok=True, daily_halted=False)
    assert should_open(direction="buy", **base) is True
    assert should_open(direction=None, **base) is False
    assert should_open(direction="buy", **{**base, "daily_halted": True}) is False
    assert should_open(direction="buy", **{**base, "cooldown_ok": False}) is False
    # Thin session blocks entries.
    assert should_open(direction="buy", **{**base, "liquidity_ok": False}) is False
    # At the per-symbol cap (>=) → no more adds.
    assert should_open(direction="buy", **{**base, "open_on_symbol": 6}) is False
    assert should_open(direction="buy", **{**base, "open_on_symbol": 5}) is True
