"""Unit tests for the per-position auto-breakeven decision."""

from __future__ import annotations

from core.enums import AssetSymbol
from core.models import Position
from use_cases.auto_breakeven import (
    at_breakeven_or_better,
    protected_count,
    tickets_to_protect,
)


def _pos(
    ticket: int,
    *,
    side: str = "buy",
    open_price: float = 100.0,
    current: float = 101.0,
    profit: float = 10.0,
    sl: float | None = None,
) -> Position:
    return Position(
        symbol=AssetSymbol.USTEC,
        ticket=ticket,
        side=side,  # type: ignore[arg-type]
        volume=0.01,
        price_open=open_price,
        price_current=current,
        profit=profit,
        sl=sl,
        tp=None,
        seconds_open=60.0,
    )


def test_fires_when_profit_reaches_threshold() -> None:
    assert tickets_to_protect([_pos(1, profit=6.0)], 6.0, True) == [1]


def test_below_threshold_does_nothing() -> None:
    assert tickets_to_protect([_pos(1, profit=5.99)], 6.0, True) == []


def test_disarmed_or_bad_threshold_never_fires() -> None:
    winner = [_pos(1, profit=100.0)]
    assert tickets_to_protect(winner, 6.0, False) == []
    assert tickets_to_protect(winner, None, True) == []
    assert tickets_to_protect(winner, 0.0, True) == []


def test_skips_position_already_at_breakeven() -> None:
    """A stop already at entry (or trailed past it) must not be touched —
    re-sending entry would loosen a trailed stop."""
    assert tickets_to_protect([_pos(1, profit=50.0, sl=100.0)], 6.0, True) == []
    assert tickets_to_protect([_pos(1, profit=50.0, sl=100.5)], 6.0, True) == []
    # A stop still below entry on a long is not protection yet.
    assert tickets_to_protect([_pos(1, profit=50.0, sl=99.0)], 6.0, True) == [1]


def test_short_side_is_mirrored() -> None:
    short = _pos(1, side="sell", open_price=100.0, current=99.0, profit=10.0)
    assert tickets_to_protect([short], 6.0, True) == [1]
    safe = _pos(2, side="sell", open_price=100.0, current=99.0, profit=10.0, sl=100.0)
    assert tickets_to_protect([safe], 6.0, True) == []
    loose = _pos(3, side="sell", open_price=100.0, current=99.0, profit=10.0, sl=101.0)
    assert tickets_to_protect([loose], 6.0, True) == [3]


def test_profit_without_price_move_is_skipped() -> None:
    """Guard against a stop the broker would reject: profit can read positive
    from a swap credit while price still sits at (or under) the entry."""
    flat = _pos(1, open_price=100.0, current=100.0, profit=9.0)
    assert tickets_to_protect([flat], 6.0, True) == []


def test_no_stop_is_not_breakeven() -> None:
    assert not at_breakeven_or_better(_pos(1, sl=None))
    assert not at_breakeven_or_better(_pos(2, sl=0.0))


def test_protected_count_only_counts_safe_positions() -> None:
    positions = [_pos(1, sl=100.0), _pos(2, sl=99.0), _pos(3, sl=None)]
    assert protected_count(positions) == 1


def test_picks_only_the_positions_that_crossed() -> None:
    positions = [
        _pos(1, profit=7.0),  # crossed
        _pos(2, profit=2.0),  # not yet
        _pos(3, profit=20.0, sl=100.0),  # already safe
        _pos(4, profit=6.5),  # crossed
    ]
    assert tickets_to_protect(positions, 6.0, True) == [1, 4]
