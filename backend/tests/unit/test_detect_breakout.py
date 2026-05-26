"""Unit tests for DetectBreakoutsUseCase."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.enums import AssetSymbol, BreakoutDirection, Timeframe
from core.models import IntradayBar
from use_cases.detect_breakout import BreakoutThresholds, DetectBreakoutsUseCase


def _bar(idx: int, *, o: float, h: float, l: float, c: float, v: float = 100) -> IntradayBar:
    base = datetime(2026, 5, 26, 13, 30, tzinfo=timezone.utc)
    return IntradayBar(
        timestamp=base + timedelta(minutes=15 * idx),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=v,
    )


def _flat_bars(n: int, price: float = 100.0, atr_like: float = 1.0) -> list[IntradayBar]:
    """Generate `n` flat-ish bars around `price` with consistent range = atr_like."""
    return [
        _bar(
            i,
            o=price,
            h=price + atr_like / 2,
            l=price - atr_like / 2,
            c=price,
        )
        for i in range(n)
    ]


def test_no_signal_without_enough_bars() -> None:
    uc = DetectBreakoutsUseCase()
    bars = _flat_bars(10)  # < N+1 + atr_sma_window + atr_window
    assert uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars) == []


def test_no_signal_in_chop() -> None:
    """Steady chop: no Donchian level is breached."""
    uc = DetectBreakoutsUseCase()
    bars = _flat_bars(80, price=100, atr_like=1.0)
    assert uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars) == []


def test_long_breakout_with_squeeze() -> None:
    """A 50-bar quiet base then one expanding bar that closes above the channel."""
    uc = DetectBreakoutsUseCase()
    base = _flat_bars(60, price=100, atr_like=0.8)
    # Signal bar: range 3.0 (>> 0.8 ATR), closes above the channel high (100.4)
    signal = _bar(60, o=100.2, h=104.0, l=99.5, c=103.5)
    bars = base + [signal]
    out = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    assert len(out) == 1
    assert out[0].direction == BreakoutDirection.UP
    assert out[0].close == 103.5
    assert out[0].expansion_ratio > 1.3
    assert out[0].squeeze is True


def test_short_breakout_mirror() -> None:
    uc = DetectBreakoutsUseCase()
    base = _flat_bars(60, price=100, atr_like=0.8)
    # Signal: closes below the channel low (99.6)
    signal = _bar(60, o=99.8, h=100.5, l=96.0, c=96.5)
    bars = base + [signal]
    out = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    assert len(out) == 1
    assert out[0].direction == BreakoutDirection.DOWN
    assert out[0].close == 96.5


def test_continuation_above_level_does_not_re_signal() -> None:
    """Once price is already above the Donchian high, subsequent bars don't fire."""
    uc = DetectBreakoutsUseCase()
    base = _flat_bars(60, price=100, atr_like=0.8)
    # Bar 60: breakout (level was 100.4 in the flat base)
    s1 = _bar(60, o=100.2, h=104.0, l=99.5, c=103.5)
    # Bar 61: even higher close, but prev close was already above → no fresh cross
    s2 = _bar(61, o=103.5, h=105.0, l=103.0, c=104.5)
    bars = base + [s1, s2]
    out = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    assert len(out) == 1
    assert out[0].signal_bar_at == s1.timestamp


def test_range_too_small_rejected() -> None:
    """Close above the channel but bar range < 1.3 × ATR → reject."""
    uc = DetectBreakoutsUseCase()
    base = _flat_bars(60, price=100, atr_like=1.0)
    # Tight bar (range = 1.0 = exactly ATR, not > 1.3 ATR)
    signal = _bar(60, o=100.2, h=100.5, l=99.5, c=100.5)
    bars = base + [signal]
    out = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    assert out == []


def test_squeeze_filter_blocks_already_volatile_break() -> None:
    """Squeeze required: if ATR was rising, no signal even on a clean Donchian cross."""
    uc = DetectBreakoutsUseCase()
    # Volatile base: bars expand over time → ATR > SMA(ATR) when signal hits
    expanding: list[IntradayBar] = []
    for i in range(60):
        rng = 0.5 + i * 0.02  # ATR ramping up
        expanding.append(_bar(i, o=100, h=100 + rng / 2, l=100 - rng / 2, c=100))
    signal = _bar(60, o=100.2, h=104.0, l=99.5, c=103.5)
    bars = expanding + [signal]
    out = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    assert out == []


def test_signal_id_is_stable() -> None:
    """The same bar should produce the same id across two detector runs."""
    uc = DetectBreakoutsUseCase()
    base = _flat_bars(60, price=100, atr_like=0.8)
    signal = _bar(60, o=100.2, h=104.0, l=99.5, c=103.5)
    bars = base + [signal]
    a = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    b = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    assert len(a) == 1
    assert len(b) == 1
    assert a[0].id == b[0].id


def test_id_differs_by_asset_or_timeframe() -> None:
    uc = DetectBreakoutsUseCase()
    base = _flat_bars(60, price=100, atr_like=0.8)
    signal = _bar(60, o=100.2, h=104.0, l=99.5, c=103.5)
    bars = base + [signal]
    a = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    b = uc.execute(AssetSymbol.SPX, Timeframe.M15, bars)
    c = uc.execute(AssetSymbol.USTEC, Timeframe.H1, bars)
    assert a[0].id != b[0].id
    assert a[0].id != c[0].id


def test_squeeze_disabled_allows_break_in_volatile_market() -> None:
    """With require_squeeze=False, a Donchian break in a volatile market fires."""
    uc = DetectBreakoutsUseCase(BreakoutThresholds(require_squeeze=False))
    expanding: list[IntradayBar] = []
    for i in range(60):
        rng = 0.5 + i * 0.02
        expanding.append(_bar(i, o=100, h=100 + rng / 2, l=100 - rng / 2, c=100))
    signal = _bar(60, o=100.2, h=104.0, l=99.5, c=103.5)
    bars = expanding + [signal]
    out = uc.execute(AssetSymbol.USTEC, Timeframe.M15, bars)
    assert len(out) == 1
    assert out[0].squeeze is False
