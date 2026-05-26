"""Unit tests for ComputeIntradayLevelsUseCase."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.models import IntradayBar
from use_cases.compute_intraday_levels import ComputeIntradayLevelsUseCase


def _bar(
    minutes_from_open: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
    base_day: int = 26,
) -> IntradayBar:
    base = datetime(2026, 5, base_day, 13, 30, tzinfo=timezone.utc)  # 09:30 ET EDT
    return IntradayBar(
        timestamp=base + timedelta(minutes=minutes_from_open),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_returns_none_for_empty_bars() -> None:
    uc = ComputeIntradayLevelsUseCase()
    assert uc.execute("USTEC", []) is None


def test_computes_hod_lod_and_last_price() -> None:
    uc = ComputeIntradayLevelsUseCase()
    bars = [
        _bar(0, open_=100, high=102, low=99, close=101),
        _bar(5, open_=101, high=105, low=100, close=104),
        _bar(10, open_=104, high=104.5, low=98, close=99.5),
    ]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.hod == 105
    assert levels.lod == 98
    assert levels.last_price == 99.5
    assert levels.symbol == "USTEC"


def test_vwap_is_volume_weighted() -> None:
    uc = ComputeIntradayLevelsUseCase()
    # Same typical price (=100) on first bar with vol 1000, then typical=200 vol 3000
    bars = [
        _bar(0, open_=100, high=100, low=100, close=100, volume=1000),
        _bar(5, open_=200, high=200, low=200, close=200, volume=3000),
    ]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    # (100*1000 + 200*3000) / 4000 = 700_000 / 4000 = 175
    assert levels.vwap == pytest.approx(175.0)


def test_opening_range_uses_first_window() -> None:
    uc = ComputeIntradayLevelsUseCase(opening_range_minutes=15)
    bars = [
        _bar(0, open_=100, high=102, low=99, close=101),
        _bar(5, open_=101, high=103, low=100, close=102),
        _bar(10, open_=102, high=104, low=101, close=103),
        _bar(15, open_=103, high=110, low=102, close=109),  # outside OR
        _bar(20, open_=109, high=110, low=95, close=96),  # outside OR
    ]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.orh == 104  # max high of first 3 bars (0,5,10)
    assert levels.orl == 99  # min low of first 3 bars


def test_previous_day_pdc_pdh_pdl() -> None:
    uc = ComputeIntradayLevelsUseCase()
    prev_bars = [
        _bar(0, open_=90, high=95, low=88, close=92, base_day=25),
        _bar(5, open_=92, high=96, low=91, close=94, base_day=25),
    ]
    today_bars = [
        _bar(0, open_=100, high=102, low=99, close=101),
    ]
    levels = uc.execute("USTEC", prev_bars + today_bars)
    assert levels is not None
    assert levels.pdc == 94
    assert levels.pdh == 96
    assert levels.pdl == 88


def test_ema9_with_just_enough_bars() -> None:
    uc = ComputeIntradayLevelsUseCase()
    bars = [_bar(i * 5, open_=100 + i, high=101 + i, low=99 + i, close=100 + i) for i in range(9)]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.ema_9 is not None
    # All bars rising by 1 → EMA = mean of first 9 = 104 (closes 100..108)
    assert levels.ema_9 == pytest.approx(104.0)


def test_emas_none_when_insufficient_bars() -> None:
    uc = ComputeIntradayLevelsUseCase()
    bars = [_bar(i * 5, open_=100, high=101, low=99, close=100) for i in range(5)]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.ema_9 is None
    assert levels.ema_20 is None


def test_atr_requires_15_bars() -> None:
    uc = ComputeIntradayLevelsUseCase()
    bars = [_bar(i * 5, open_=100, high=102, low=98, close=100) for i in range(15)]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    # All TRs = max(102-98, ...) = 4 → ATR(14) = 4
    assert levels.atr_14 == pytest.approx(4.0)


def test_atr_none_when_too_few_bars() -> None:
    uc = ComputeIntradayLevelsUseCase()
    bars = [_bar(i * 5, open_=100, high=102, low=98, close=100) for i in range(10)]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.atr_14 is None


def test_last_swing_detected_with_5_bar_pivot() -> None:
    uc = ComputeIntradayLevelsUseCase()
    # Bar 2 is swing high (110 > 100,105,105,100); bar 5 is swing low (94 < 95,100,97,99).
    bars = [
        _bar(0, open_=100, high=100, low=99, close=100),
        _bar(5, open_=100, high=105, low=99, close=104),
        _bar(10, open_=104, high=110, low=103, close=109),  # ← swing high
        _bar(15, open_=109, high=105, low=100, close=101),
        _bar(20, open_=101, high=102, low=95, close=96),
        _bar(25, open_=96, high=100, low=94, close=98),  # ← swing low
        _bar(30, open_=98, high=103, low=97, close=102),
        _bar(35, open_=102, high=104, low=99, close=103),
    ]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.last_swing_high == 110
    assert levels.last_swing_low == 94


def test_no_swing_when_not_enough_bars() -> None:
    uc = ComputeIntradayLevelsUseCase()
    bars = [_bar(i * 5, open_=100, high=101, low=99, close=100) for i in range(3)]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.last_swing_high is None
    assert levels.last_swing_low is None


def test_ma200_none_when_insufficient_bars() -> None:
    uc = ComputeIntradayLevelsUseCase()
    bars = [_bar(i * 5, open_=100, high=101, low=99, close=100) for i in range(50)]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.ema_200 is None
    assert levels.sma_200 is None


def test_ma200_with_exactly_200_bars() -> None:
    uc = ComputeIntradayLevelsUseCase()
    # 200 bars at close=100 → SMA200=100, EMA200=100.
    bars = [_bar(i * 5, open_=100, high=100, low=100, close=100) for i in range(200)]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.sma_200 == pytest.approx(100.0)
    assert levels.ema_200 == pytest.approx(100.0)


def test_sma200_takes_last_200_closes() -> None:
    uc = ComputeIntradayLevelsUseCase()
    # 201 bars: first one has close=0, the other 200 have close=100.
    # SMA200 should ignore the first and equal 100.
    bars = [_bar(0, open_=100, high=100, low=100, close=0)]
    bars += [_bar((i + 1) * 5, open_=100, high=100, low=100, close=100) for i in range(200)]
    levels = uc.execute("USTEC", bars)
    assert levels is not None
    assert levels.sma_200 == pytest.approx(100.0)
