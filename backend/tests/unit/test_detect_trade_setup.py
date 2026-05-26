"""Unit tests for DetectTradeSetupUseCase."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import AssetSymbol, BiasLevel
from core.models import BiasComponents, BiasReport, IntradayLevels
from use_cases.detect_trade_setup import DetectTradeSetupUseCase, SetupThresholds


def _levels(
    *,
    last: float = 100.0,
    ema_9: float | None = 99.5,
    ema_20: float | None = 99.0,
    ema_50: float | None = 98.0,
    ema_200: float | None = 95.0,
    sma_200: float | None = 94.5,
    vwap: float | None = 98.5,
    atr_14: float | None = 1.0,
    last_swing_low: float | None = 96.0,
    last_swing_high: float | None = 105.0,
    pdh: float | None = 104.0,
    pdl: float | None = 90.0,
    hod: float | None = 101.0,
    lod: float | None = 97.0,
) -> IntradayLevels:
    asof = datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc)
    return IntradayLevels(
        symbol="USTEC",
        asof=asof,
        last_price=last,
        hod=hod or last,
        lod=lod or last,
        vwap=vwap,
        orh=None,
        orl=None,
        pdc=None,
        pdh=pdh,
        pdl=pdl,
        ema_9=ema_9,
        ema_20=ema_20,
        ema_50=ema_50,
        ema_200=ema_200,
        sma_200=sma_200,
        atr_14=atr_14,
        last_swing_high=last_swing_high,
        last_swing_high_at=asof,
        last_swing_low=last_swing_low,
        last_swing_low_at=asof,
    )


def _bias(score: float, level: BiasLevel, asset: AssetSymbol = AssetSymbol.USTEC) -> BiasReport:
    return BiasReport(
        asset=asset,
        timestamp=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
        score=score,
        level=level,
        components=BiasComponents(technical=70, macro=60, sentiment=55),
    )


def test_no_setup_when_lateral_score() -> None:
    uc = DetectTradeSetupUseCase()
    assert uc.execute(_levels(), _bias(50, BiasLevel.NEUTRAL)) is None
    assert uc.execute(_levels(), _bias(55, BiasLevel.NEUTRAL)) is None
    assert uc.execute(_levels(), _bias(45, BiasLevel.NEUTRAL)) is None


def test_no_setup_when_intraday_data_missing() -> None:
    uc = DetectTradeSetupUseCase()
    lv = _levels(ema_200=None)
    assert uc.execute(lv, _bias(70, BiasLevel.BULLISH)) is None


def test_long_setup_emitted_on_full_confluence() -> None:
    uc = DetectTradeSetupUseCase()
    # last=100, all MAs and VWAP below. PDH=104, swing_low=96, ATR=1
    # Pullback nearest = ema_9 (99.5), within 0.75*ATR (0.75). Distance 0.5 — OK
    # Stop = 96 - 0.25 = 95.75 → risk = 4.25
    # Target candidates: PDH 104, HOD 101, swing_high 105, last+4*1=104. min=101
    # Reward = 1 → RR = 0.24 → fails min_rr=2
    # Need a wider target or tighter stop. Let me tune the levels.
    lv = _levels(
        last=100,
        ema_9=99.5,
        ema_20=99.0,
        vwap=98.5,
        last_swing_low=99.0,
        pdh=110.0,
        hod=110.0,
        last_swing_high=110.0,
    )
    setup = uc.execute(lv, _bias(65, BiasLevel.BULLISH))
    assert setup is not None
    assert setup.direction == "LONG"
    assert setup.entry_zone_low <= setup.entry_zone_high
    assert setup.stop_level < setup.entry_zone_low
    assert setup.target_level > setup.entry_zone_high
    assert setup.risk_reward >= 2.0


def test_long_rejected_when_price_below_ema200() -> None:
    uc = DetectTradeSetupUseCase()
    lv = _levels(last=94.0)  # below ema_200=95
    assert uc.execute(lv, _bias(65, BiasLevel.BULLISH)) is None


def test_long_rejected_when_price_below_vwap() -> None:
    uc = DetectTradeSetupUseCase()
    lv = _levels(last=98.0, vwap=99.0)
    assert uc.execute(lv, _bias(65, BiasLevel.BULLISH)) is None


def test_long_rejected_when_chasing_top() -> None:
    """Price extended way above the nearest mean (no pullback)."""
    uc = DetectTradeSetupUseCase()
    # ATR=1, pullback window 0.75. Price 105, nearest below = ema_9=99.5 → dist 5.5 > 0.75
    lv = _levels(last=105, ema_9=99.5, ema_20=99.0, vwap=98.5, last_swing_low=99.0, pdh=120.0)
    assert uc.execute(lv, _bias(65, BiasLevel.BULLISH)) is None


def test_long_rejected_when_rr_below_threshold() -> None:
    uc = DetectTradeSetupUseCase()
    # Tight target → low RR. HOD=100.5 is the closest resistance.
    lv = _levels(last=100, ema_9=99.5, last_swing_low=99.0, pdh=100.5, hod=100.5)
    assert uc.execute(lv, _bias(65, BiasLevel.BULLISH)) is None


def test_short_setup_emitted_on_full_confluence() -> None:
    uc = DetectTradeSetupUseCase()
    # Mirror: price below all means, swing high above, target = PDL way below
    lv = _levels(
        last=100,
        ema_9=100.5,
        ema_20=101.0,
        ema_50=102.0,
        ema_200=105.0,
        sma_200=105.5,
        vwap=101.0,
        last_swing_high=101.0,
        pdl=90.0,
    )
    setup = uc.execute(lv, _bias(30, BiasLevel.BEARISH))
    assert setup is not None
    assert setup.direction == "SHORT"
    assert setup.entry_zone_low <= setup.entry_zone_high
    assert setup.stop_level > setup.entry_zone_high
    assert setup.target_level < setup.entry_zone_low
    assert setup.risk_reward >= 2.0


def test_short_rejected_when_price_above_ema200() -> None:
    uc = DetectTradeSetupUseCase()
    lv = _levels(last=106, ema_200=105.0, sma_200=105.5)
    assert uc.execute(lv, _bias(30, BiasLevel.BEARISH)) is None


def test_long_rationale_mentions_key_factors() -> None:
    uc = DetectTradeSetupUseCase()
    lv = _levels(
        last=100,
        ema_9=99.5,
        ema_20=99.0,
        vwap=98.5,
        last_swing_low=99.0,
        pdh=110.0,
        hod=110.0,
        last_swing_high=110.0,
    )
    setup = uc.execute(lv, _bias(70, BiasLevel.BULLISH))
    assert setup is not None
    joined = " ".join(setup.rationale).lower()
    assert "score" in joined
    assert "vwap" in joined or "ema" in joined
    assert "r:r" in joined or "r/r" in joined or "rr" in joined or "alvo" in joined


def test_continuation_label_high_for_strong_setup() -> None:
    uc = DetectTradeSetupUseCase()
    lv = _levels(
        last=100,
        ema_9=99.5,
        ema_20=99.0,
        vwap=98.5,
        last_swing_low=99.0,
        pdh=120.0,
        hod=120.0,
        last_swing_high=120.0,
    )
    setup = uc.execute(lv, _bias(80, BiasLevel.BULLISH))
    assert setup is not None
    assert (
        "alta probabilidade" in setup.continuation_label.lower()
        or "boa" in setup.continuation_label.lower()
    )


def test_custom_thresholds_can_be_tighter() -> None:
    """Validate threshold tuning works (e.g., demanding RR>=3)."""
    uc = DetectTradeSetupUseCase(thresholds=SetupThresholds(min_risk_reward=10.0))
    lv = _levels(
        last=100,
        ema_9=99.5,
        ema_20=99.0,
        vwap=98.5,
        last_swing_low=99.0,
        pdh=110.0,
        hod=110.0,
        last_swing_high=110.0,
    )
    assert uc.execute(lv, _bias(70, BiasLevel.BULLISH)) is None


def test_score_at_boundary_long() -> None:
    uc = DetectTradeSetupUseCase()
    lv = _levels(
        last=100,
        ema_9=99.5,
        ema_20=99.0,
        vwap=98.5,
        last_swing_low=99.0,
        pdh=110.0,
        hod=110.0,
        last_swing_high=110.0,
    )
    # Exactly 60 → ALTA, must accept
    assert uc.execute(lv, _bias(60, BiasLevel.BULLISH)) is not None
    # 59 → LATERAL, must reject
    assert uc.execute(lv, _bias(59, BiasLevel.NEUTRAL)) is None


@pytest.mark.parametrize(
    "score,expected_dir",
    [(75, "LONG"), (25, "SHORT"), (50, None)],
)
def test_direction_decided_by_score(score: float, expected_dir: str | None) -> None:
    uc = DetectTradeSetupUseCase()
    if expected_dir == "LONG":
        lv = _levels(
            last=100,
            ema_9=99.5,
            ema_20=99.0,
            vwap=98.5,
            last_swing_low=99.0,
            pdh=110.0,
            hod=110.0,
            last_swing_high=110.0,
        )
        bias = _bias(score, BiasLevel.BULLISH)
    elif expected_dir == "SHORT":
        lv = _levels(
            last=100,
            ema_9=100.5,
            ema_20=101.0,
            ema_50=102.0,
            ema_200=105.0,
            sma_200=105.5,
            vwap=101.0,
            last_swing_high=101.0,
            pdl=90.0,
        )
        bias = _bias(score, BiasLevel.BEARISH)
    else:
        lv = _levels()
        bias = _bias(score, BiasLevel.NEUTRAL)

    setup = uc.execute(lv, bias)
    if expected_dir is None:
        assert setup is None
    else:
        assert setup is not None
        assert setup.direction == expected_dir
