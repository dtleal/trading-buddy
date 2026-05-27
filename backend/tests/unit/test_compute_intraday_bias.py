"""Unit tests for ComputeIntradayBiasUseCase."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import AssetSymbol, BiasLevel
from core.models import IntradayLevels
from use_cases.compute_intraday_bias import ComputeIntradayBiasUseCase


def _levels(
    *,
    last: float = 100.0,
    vwap: float | None = 100.0,
    ema_9: float | None = 100.0,
    ema_20: float | None = 100.0,
    ema_50: float | None = 100.0,
    ema_200: float | None = 100.0,
    sma_200: float | None = 100.0,
) -> IntradayLevels:
    ts = datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc)
    return IntradayLevels(
        symbol="USTEC",
        asof=ts,
        last_price=last,
        hod=last,
        lod=last,
        vwap=vwap,
        orh=None,
        orl=None,
        pdc=None,
        pdh=None,
        pdl=None,
        ema_9=ema_9,
        ema_20=ema_20,
        ema_50=ema_50,
        ema_200=ema_200,
        sma_200=sma_200,
        atr_14=1.0,
        last_swing_high=None,
        last_swing_high_at=None,
        last_swing_low=None,
        last_swing_low_at=None,
    )


def test_all_means_equal_to_price_yields_neutral_50() -> None:
    uc = ComputeIntradayBiasUseCase()
    out = uc.execute(
        AssetSymbol.USTEC,
        _levels(last=100, vwap=100, ema_9=100, ema_20=100, ema_50=100, ema_200=100, sma_200=100),
    )
    assert out.score == pytest.approx(50.0)
    assert out.level == BiasLevel.NEUTRAL


def test_price_above_everything_is_bullish_100() -> None:
    uc = ComputeIntradayBiasUseCase()
    out = uc.execute(
        AssetSymbol.USTEC,
        _levels(last=110, vwap=100, ema_9=99, ema_20=98, ema_50=97, ema_200=95, sma_200=94),
    )
    # +30 + 20 + 20 + 15 + 15 = +100 → mapped to (50 + 100/2) = 100
    assert out.score == pytest.approx(100.0)
    assert out.level == BiasLevel.BULLISH


def test_price_below_everything_is_bearish_0() -> None:
    uc = ComputeIntradayBiasUseCase()
    out = uc.execute(
        AssetSymbol.USTEC,
        _levels(last=90, vwap=100, ema_9=101, ema_20=102, ema_50=103, ema_200=105, sma_200=106),
    )
    # -30 - 20 - 20 - 15 - 15 = -100 → 0
    assert out.score == pytest.approx(0.0)
    assert out.level == BiasLevel.BEARISH


def test_below_vwap_but_above_long_means_mixed() -> None:
    """Mimics the user's observed case — price dropped below VWAP but is
    still above the slow 5m MAs. Score should reflect mid-territory bearish
    lean (not full bear)."""
    uc = ComputeIntradayBiasUseCase()
    out = uc.execute(
        AssetSymbol.USTEC,
        _levels(
            last=99,
            vwap=100,  # below → -30
            ema_9=98,  # above → +15
            ema_20=97,  # above → +15
            ema_50=96,  # above → +15  (no, EMA50 is not in the weights)
            ema_200=90,  # above → +20
            sma_200=89,  # above → +20
        ),
    )
    # EMA50 is not weighted; sum = -30 +15 +15 +20 +20 = +40 → 50 + 40/2 = 70
    assert out.score == pytest.approx(70.0)


def test_missing_long_means_dont_blow_up() -> None:
    """First 30 min of session: EMA 200 / SMA 200 not computed yet."""
    uc = ComputeIntradayBiasUseCase()
    out = uc.execute(
        AssetSymbol.USTEC,
        _levels(last=110, vwap=100, ema_9=99, ema_20=98, ema_50=None, ema_200=None, sma_200=None),
    )
    # +30 + 15 + 15 = +60 → 50 + 30 = 80
    assert out.score == pytest.approx(80.0)
    assert out.level == BiasLevel.BULLISH
    assert "EMA 200 (5m) indisponível" in out.signals
    assert "SMA 200 (5m) indisponível" in out.signals


def test_signals_describe_position() -> None:
    uc = ComputeIntradayBiasUseCase()
    out = uc.execute(
        AssetSymbol.USTEC,
        _levels(last=99, vwap=100, ema_9=98, ema_20=98, ema_200=98, sma_200=98),
    )
    sigs = " ".join(out.signals)
    assert "abaixo VWAP" in sigs
    assert "acima EMA 9" in sigs


def test_boundary_60_is_bullish() -> None:
    uc = ComputeIntradayBiasUseCase()
    # We need score exactly 60. +20 net → 50 + 10 = 60.
    # weights: 30 above VWAP + (-15 below EMA9) + (-15 below EMA20) + (+20 EMA200) + (+0 SMA200 if equal)... tricky
    # Simpler path: only VWAP set and price above → +30 → 50 + 15 = 65 (not 60)
    # Let's craft: above VWAP (+30), above SMA200 (+20), below EMA9 (-15), below EMA20 (-15), EMA200=last (0)
    out = uc.execute(
        AssetSymbol.USTEC,
        _levels(last=100, vwap=99, ema_9=101, ema_20=101, ema_200=100, sma_200=99),
    )
    # +30 - 15 - 15 + 0 + 20 = +20 → 60
    assert out.score == pytest.approx(60.0)
    assert out.level == BiasLevel.BULLISH


def test_boundary_40_is_bearish() -> None:
    uc = ComputeIntradayBiasUseCase()
    out = uc.execute(
        AssetSymbol.USTEC,
        _levels(last=100, vwap=101, ema_9=99, ema_20=99, ema_200=100, sma_200=101),
    )
    # -30 + 15 + 15 + 0 - 20 = -20 → 40
    assert out.score == pytest.approx(40.0)
    assert out.level == BiasLevel.BEARISH
