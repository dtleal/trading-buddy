from __future__ import annotations

import pytest

from day_trading_buddy.core.enums import AssetSymbol, TermStructure, VixRegime
from day_trading_buddy.core.models import MarketSnapshot, PriceQuote, VixSnapshot
from day_trading_buddy.use_cases.compute_technical_bias import ComputeTechnicalBiasUseCase


@pytest.mark.asyncio
async def test_price_above_ma200_is_bullish(market_snapshot: MarketSnapshot) -> None:
    result = await ComputeTechnicalBiasUseCase().execute(market_snapshot)
    assert result[AssetSymbol.USTEC].score > 50.0
    assert any("MA200" in r for r in result[AssetSymbol.USTEC].rationale)


@pytest.mark.asyncio
async def test_high_vix_penalises_stocks(now, market_snapshot: MarketSnapshot) -> None:
    stressed = market_snapshot.model_copy(
        update={
            "vix": VixSnapshot(
                vix=30.0,
                vix9d=32.0,
                vix3m=29.0,
                regime=VixRegime.HIGH,
                term_structure=TermStructure.BACKWARDATION,
            )
        }
    )
    result = await ComputeTechnicalBiasUseCase().execute(stressed)
    assert result[AssetSymbol.USTEC].score < result[AssetSymbol.GOLD].score


@pytest.mark.asyncio
async def test_score_is_clipped_to_unit_range() -> None:
    snapshot = MarketSnapshot(
        timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        assets={
            AssetSymbol.USTEC: PriceQuote(
                symbol="USTEC",
                price=100.0,
                timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                ma200_d=1.0,  # huge distance — would overshoot without clipping
            )
        },
        vix=VixSnapshot(
            vix=10.0,
            vix9d=None,
            vix3m=None,
            regime=VixRegime.LOW,
            term_structure=TermStructure.FLAT,
        ),
    )
    result = await ComputeTechnicalBiasUseCase().execute(snapshot)
    assert 0.0 <= result[AssetSymbol.USTEC].score <= 100.0
