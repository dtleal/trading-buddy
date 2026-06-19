"""Unit tests for the day-outlook gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.enums import AssetSymbol, DayRegime, ImpactLevel, TermStructure, VixRegime
from core.models import EconomicEvent, IntradayLevels, SessionLiquidity, VixSnapshot
from use_cases.assess_day_outlook import AssessDayOutlookUseCase

NOW = datetime(2026, 6, 19, 13, 0, tzinfo=timezone.utc)


def _event(name: str, impact: ImpactLevel, *, currency: str = "USD", hour: int = 12) -> EconomicEvent:
    return EconomicEvent(
        name=name,
        currency=currency,
        impact=impact,
        scheduled_at=NOW.replace(hour=hour, minute=0),
    )


def _vix(regime: VixRegime, value: float = 18.0) -> VixSnapshot:
    return VixSnapshot(
        vix=value,
        vix9d=None,
        vix3m=None,
        regime=regime,
        term_structure=TermStructure.CONTANGO,
    )


def _liq(
    symbol: AssetSymbol, ratio: float, range_ratio: float | None = None
) -> SessionLiquidity:
    return SessionLiquidity(
        symbol=symbol,
        asof=NOW,
        realized_volume=ratio * 1000.0,
        baseline_volume=1000.0,
        ratio=ratio,
        sample_days=20,
        realized_range=(range_ratio * 50.0) if range_ratio is not None else None,
        baseline_range=50.0 if range_ratio is not None else None,
        range_ratio=range_ratio,
    )


def test_us_holiday_no_catalyst_is_thin() -> None:
    """Today's real case: US bank holiday + zero high-impact events → FRACO."""
    uc = AssessDayOutlookUseCase()
    out = uc.execute(
        now=NOW,
        events_today=[_event("Bank Holiday", ImpactLevel.HOLIDAY)],
        vix=_vix(VixRegime.LOW, 12.5),
    )
    assert out.regime is DayRegime.THIN
    assert out.is_us_holiday is True
    assert out.score < 38
    assert "Feriado" in " ".join(out.rationale)
    assert "FRACO" in out.headline


def test_upcoming_high_impact_is_expansion() -> None:
    """A CPI day with the release still ahead and live vol → EXPANSÃO."""
    uc = AssessDayOutlookUseCase()
    out = uc.execute(
        now=NOW,
        events_today=[
            _event("CPI YoY", ImpactLevel.HIGH, hour=12),  # 12:00 < now? NOW is 13:00
            _event("FOMC Statement", ImpactLevel.HIGH, hour=18),  # ahead of NOW
        ],
        vix=_vix(VixRegime.HIGH, 28.0),
    )
    assert out.regime is DayRegime.EXPANSION
    assert out.high_impact_count == 2
    assert out.score >= 64


def test_ordinary_day_is_normal() -> None:
    uc = AssessDayOutlookUseCase()
    out = uc.execute(
        now=NOW,
        events_today=[_event("Some Medium Thing", ImpactLevel.MEDIUM)],
        vix=_vix(VixRegime.MID, 18.0),
    )
    assert out.regime is DayRegime.NORMAL


def test_low_mt5_liquidity_drags_score_down() -> None:
    """Even absent a holiday, collapsing tick volume should warn THIN."""
    uc = AssessDayOutlookUseCase()
    base = uc.execute(now=NOW, events_today=[], vix=_vix(VixRegime.MID))
    thin = uc.execute(
        now=NOW,
        events_today=[],
        vix=_vix(VixRegime.MID),
        liquidity={
            AssetSymbol.USTEC: _liq(AssetSymbol.USTEC, 0.35),
            AssetSymbol.SPX: _liq(AssetSymbol.SPX, 0.40),
        },
    )
    assert thin.score < base.score
    assert thin.liquidity_ratio is not None and thin.liquidity_ratio < 0.5
    assert "Atividade muito baixa" in " ".join(thin.rationale)


def test_tiny_candles_drag_score_even_with_normal_volume() -> None:
    """Volume normal but session range tiny ('21 candles minúsculos') → the
    worse-of rule must still flag the day as thin."""
    uc = AssessDayOutlookUseCase()
    out = uc.execute(
        now=NOW,
        events_today=[],
        vix=_vix(VixRegime.MID),
        liquidity={
            AssetSymbol.USTEC: _liq(AssetSymbol.USTEC, 1.0, range_ratio=0.30),
            AssetSymbol.SPX: _liq(AssetSymbol.SPX, 0.95, range_ratio=0.35),
        },
    )
    assert "Atividade muito baixa" in " ".join(out.rationale)
    assert "candles" in " ".join(out.rationale)
    assert out.regime is DayRegime.THIN


def test_opening_range_compression_penalized() -> None:
    uc = AssessDayOutlookUseCase()

    def _levels(or_width: float, atr: float) -> dict[AssetSymbol, IntradayLevels]:
        lv = IntradayLevels(
            symbol="USTEC",
            asof=NOW,
            last_price=100.0,
            hod=101.0,
            lod=99.0,
            vwap=None,
            orh=100.0 + or_width / 2,
            orl=100.0 - or_width / 2,
            pdc=None,
            pdh=None,
            pdl=None,
            ema_9=None,
            ema_20=None,
            ema_50=None,
            ema_200=None,
            sma_200=None,
            atr_14=atr,
            last_swing_high=None,
            last_swing_high_at=None,
            last_swing_low=None,
            last_swing_low_at=None,
        )
        return {AssetSymbol.USTEC: lv}

    compressed = uc.execute(
        now=NOW, events_today=[], vix=_vix(VixRegime.MID), levels=_levels(0.2, 1.0)
    )
    expanded = uc.execute(
        now=NOW, events_today=[], vix=_vix(VixRegime.MID), levels=_levels(2.0, 1.0)
    )
    assert compressed.score < expanded.score


def test_holiday_only_drives_currency_counts() -> None:
    """A non-USD holiday should not flip the US-holiday flag."""
    uc = AssessDayOutlookUseCase()
    out = uc.execute(
        now=NOW,
        events_today=[_event("Bank Holiday", ImpactLevel.HOLIDAY, currency="CNY")],
        vix=_vix(VixRegime.MID),
    )
    assert out.is_us_holiday is False
