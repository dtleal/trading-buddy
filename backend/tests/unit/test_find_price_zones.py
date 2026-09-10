"""Unit tests for find_price_zones."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.enums import AssetSymbol
from core.models import IntradayBar
from use_cases.find_price_zones import FindPriceZonesUseCase

BASE = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)


def _bar(idx: int, *, o: float, h: float, l: float, c: float, daily: bool = False) -> IntradayBar:
    step = timedelta(days=1) if daily else timedelta(minutes=5)
    return IntradayBar(
        timestamp=BASE + step * idx,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100,
    )


def _zigzag(
    lows: list[float], *, ceiling: float, span: int = 6, daily: bool = False
) -> list[IntradayBar]:
    """Bars that rally to `ceiling` and fall back to each low in turn.

    Each leg is `span` bars up and `span` bars down, so every top is a
    confirmed swing high at `ceiling` and every bottom a swing low.
    """
    bars: list[IntradayBar] = []
    idx = 0
    for low in lows:
        for step in range(span):
            price = low + (ceiling - low) * (step + 1) / span
            bars.append(_bar(idx, o=price, h=price, l=price - 0.2, c=price, daily=daily))
            idx += 1
        for step in range(span):
            price = ceiling - (ceiling - low) * (step + 1) / span
            bars.append(_bar(idx, o=price, h=price + 0.2, l=price, c=price, daily=daily))
            idx += 1
    return bars


def test_three_touches_make_a_zone() -> None:
    """A ceiling tapped three times and never closed through is a sell zone."""
    bars = _zigzag([100.0, 100.5, 99.5, 100.2], ceiling=110.0)
    # Park price well below the ceiling so the zone reads as resistance.
    bars += [_bar(len(bars) + i, o=101, h=101.2, l=100.8, c=101) for i in range(5)]

    zones = FindPriceZonesUseCase().execute(AssetSymbol.USTEC, bars)

    sells = [z for z in zones if z.side == "sell"]
    assert sells, "the ceiling touched 4x should produce a zone"
    top = max(sells, key=lambda z: z.score)
    assert top.low <= 110.0 <= top.high
    assert top.touches >= 3
    assert top.kind in ("top", "both")
    assert "5m" in top.timeframes
    assert top.distance_pct > 0  # above price


def test_level_closed_through_is_dropped() -> None:
    """Same touches, but price closes clean through the ceiling in between."""
    bars = _zigzag([100.0, 100.5], ceiling=110.0)
    # Two closes well above the level, then more touches of the same ceiling.
    bars += [_bar(len(bars) + i, o=113, h=113.5, l=112.5, c=113) for i in range(4)]
    tail = _zigzag([100.2, 99.8], ceiling=110.0)
    bars += [
        _bar(len(bars) + i, o=b.open, h=b.high, l=b.low, c=b.close) for i, b in enumerate(tail)
    ]
    bars += [_bar(len(bars) + i, o=101, h=101.2, l=100.8, c=101) for i in range(5)]

    zones = FindPriceZonesUseCase().execute(AssetSymbol.USTEC, bars)

    pierced = [z for z in zones if z.low <= 110.0 <= z.high and z.kind == "top"]
    assert not pierced, "a level price closed through twice is not a level"


def test_two_touches_is_not_a_zone() -> None:
    bars = _zigzag([100.0, 100.4], ceiling=110.0)
    bars += [_bar(len(bars) + i, o=101, h=101.2, l=100.8, c=101) for i in range(5)]

    zones = FindPriceZonesUseCase().execute(AssetSymbol.USTEC, bars)

    assert not [z for z in zones if z.low <= 110.0 <= z.high]


def test_daily_confluence_scores_higher() -> None:
    """The same level on the daily and on the 5m outranks a 5m-only level."""
    intraday = _zigzag([100.0, 100.5, 99.5], ceiling=110.0)
    # A separate 5m-only ceiling further up, touched just as often.
    intraday += _zigzag([112.0, 112.5, 111.8], ceiling=120.0)
    intraday += [_bar(len(intraday) + i, o=101, h=101.2, l=100.8, c=101) for i in range(5)]
    daily = _zigzag([90.0, 92.0, 91.0], ceiling=110.0, daily=True)

    zones = FindPriceZonesUseCase().execute(AssetSymbol.USTEC, intraday, daily)

    shared = next(z for z in zones if z.low <= 110.0 <= z.high)
    solo = next(z for z in zones if z.low <= 120.0 <= z.high)
    assert "1d" in shared.timeframes
    assert shared.score > solo.score
    assert shared.strength >= solo.strength


def test_no_bars_no_zones() -> None:
    assert FindPriceZonesUseCase().execute(AssetSymbol.GOLD, []) == []
