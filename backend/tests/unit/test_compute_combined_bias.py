from __future__ import annotations

import pytest

from day_trading_buddy.core.enums import AssetSymbol, BiasLevel
from day_trading_buddy.use_cases.compute_combined_bias import (
    BiasThresholds,
    BiasWeights,
    ComputeCombinedBiasUseCase,
)
from day_trading_buddy.use_cases.compute_macro_signal import MacroBias
from day_trading_buddy.use_cases.compute_news_sentiment import SentimentBias
from day_trading_buddy.use_cases.compute_technical_bias import TechnicalBias


def _weights() -> BiasWeights:
    return BiasWeights(technical=0.4, macro=0.3, sentiment=0.3)


def _thresholds() -> BiasThresholds:
    return BiasThresholds(bullish=60.0, bearish=40.0)


@pytest.mark.asyncio
async def test_all_neutral_yields_neutral_level() -> None:
    uc = ComputeCombinedBiasUseCase(_weights(), _thresholds())
    bias = await uc.execute(
        technical={a: TechnicalBias(score=50.0, rationale=[]) for a in AssetSymbol},
        macro={a: MacroBias(score=50.0, rationale=[]) for a in AssetSymbol},
        sentiment={
            a: SentimentBias(score=50.0, classified_count=0, rationale=[]) for a in AssetSymbol
        },
    )
    for report in bias.values():
        assert report.level == BiasLevel.NEUTRAL
        assert report.score == 50.0


@pytest.mark.asyncio
async def test_bullish_when_above_threshold() -> None:
    uc = ComputeCombinedBiasUseCase(_weights(), _thresholds())
    bias = await uc.execute(
        technical={AssetSymbol.SPX: TechnicalBias(score=80.0, rationale=["trend up"])},
        macro={AssetSymbol.SPX: MacroBias(score=80.0, rationale=["cuts coming"])},
        sentiment={AssetSymbol.SPX: SentimentBias(score=80.0, classified_count=5, rationale=[])},
    )
    assert bias[AssetSymbol.SPX].level == BiasLevel.BULLISH
    assert bias[AssetSymbol.SPX].score == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_bearish_when_below_threshold() -> None:
    uc = ComputeCombinedBiasUseCase(_weights(), _thresholds())
    bias = await uc.execute(
        technical={AssetSymbol.GOLD: TechnicalBias(score=20.0, rationale=[])},
        macro={AssetSymbol.GOLD: MacroBias(score=20.0, rationale=[])},
        sentiment={AssetSymbol.GOLD: SentimentBias(score=20.0, classified_count=0, rationale=[])},
    )
    assert bias[AssetSymbol.GOLD].level == BiasLevel.BEARISH
