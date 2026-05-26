"""Unit tests for resample_bars."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.enums import Timeframe
from core.models import IntradayBar
from use_cases.resample_bars import resample_to


def _bar(idx: int, *, o: float, h: float, l: float, c: float, v: float = 100) -> IntradayBar:
    base = datetime(2026, 5, 26, 13, 30, tzinfo=timezone.utc)
    return IntradayBar(
        timestamp=base + timedelta(minutes=5 * idx),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def test_m5_passthrough() -> None:
    bars = [_bar(i, o=100, h=101, l=99, c=100) for i in range(5)]
    out = resample_to(bars, Timeframe.M5)
    assert len(out) == 5
    assert out == list(bars)


def test_m15_groups_3_bars() -> None:
    bars = [
        _bar(0, o=100, h=101, l=99, c=100.5),
        _bar(1, o=100.5, h=102, l=100, c=101),
        _bar(2, o=101, h=103, l=100.5, c=102.5),
        _bar(3, o=102.5, h=104, l=102, c=103),
        _bar(4, o=103, h=104.5, l=102.5, c=104),
        _bar(5, o=104, h=105, l=103, c=104.5),
    ]
    out = resample_to(bars, Timeframe.M15)
    assert len(out) == 2
    # First group: bars 0..2
    assert out[0].open == 100
    assert out[0].high == 103
    assert out[0].low == 99
    assert out[0].close == 102.5
    assert out[0].volume == 300
    # Second group: bars 3..5
    assert out[1].open == 102.5
    assert out[1].high == 105
    assert out[1].low == 102
    assert out[1].close == 104.5


def test_m30_drops_partial_trailing_group() -> None:
    # 7 bars: one full group of 6, plus 1 partial → drop the partial
    bars = [_bar(i, o=100, h=101, l=99, c=100) for i in range(7)]
    out = resample_to(bars, Timeframe.M30)
    assert len(out) == 1


def test_h4_groups_48_bars() -> None:
    bars = [_bar(i, o=100, h=101, l=99, c=100) for i in range(96)]
    out = resample_to(bars, Timeframe.H4)
    assert len(out) == 2  # 96 / 48 = 2 full groups
    assert all(b.volume == 4800 for b in out)


def test_empty_input() -> None:
    assert resample_to([], Timeframe.M15) == []


def test_fewer_than_group_size_drops_all() -> None:
    bars = [_bar(i, o=100, h=101, l=99, c=100) for i in range(2)]
    assert resample_to(bars, Timeframe.M15) == []
