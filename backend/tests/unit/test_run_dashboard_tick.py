from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import AssetSymbol
from core.models import PriceQuote
from tests.fakes import (
    FakeCalendarGateway,
    FakeMacroGateway,
    FakeNewsGateway,
    FakePricesGateway,
    FakeSentimentClassifier,
    FakeSnapshotRepository,
    InMemoryCache,
)
from use_cases.compute_combined_bias import (
    BiasThresholds,
    BiasWeights,
    ComputeCombinedBiasUseCase,
)
from use_cases.compute_macro_signal import ComputeMacroSignalUseCase
from use_cases.compute_news_sentiment import ComputeNewsSentimentUseCase
from use_cases.compute_technical_bias import ComputeTechnicalBiasUseCase
from use_cases.fetch_calendar import FetchEconomicCalendarUseCase
from use_cases.fetch_macro import FetchMacroIndicatorsUseCase
from use_cases.fetch_market import FetchMarketSnapshotUseCase
from use_cases.fetch_news import FetchNewsHeadlinesUseCase
from use_cases.run_dashboard_tick import RunDashboardTickUseCase


@pytest.mark.asyncio
async def test_full_tick_pipeline_produces_bias_for_every_asset() -> None:
    now = datetime.now(timezone.utc)
    cache = InMemoryCache()
    repo = FakeSnapshotRepository()
    prices = FakePricesGateway(
        quotes={
            "USTEC": PriceQuote(symbol="USTEC", price=20_000.0, timestamp=now),
            "SPX": PriceQuote(symbol="SPX", price=5_900.0, timestamp=now),
            "GOLD": PriceQuote(symbol="GOLD", price=2_600.0, timestamp=now),
            "VIX": PriceQuote(symbol="VIX", price=15.0, timestamp=now),
            "VIX9D": PriceQuote(symbol="VIX9D", price=14.5, timestamp=now),
            "VIX3M": PriceQuote(symbol="VIX3M", price=16.0, timestamp=now),
        }
    )

    macro_primary = FakeMacroGateway()
    fedwatch = FakeMacroGateway()

    run_tick = RunDashboardTickUseCase(
        fetch_market=FetchMarketSnapshotUseCase(prices=prices, cache=cache),
        fetch_calendar=FetchEconomicCalendarUseCase(calendar=FakeCalendarGateway(), cache=cache),
        fetch_news=FetchNewsHeadlinesUseCase([FakeNewsGateway()]),
        fetch_macro=FetchMacroIndicatorsUseCase(
            primary=macro_primary, fedwatch=fedwatch, cache=cache
        ),
        compute_technical=ComputeTechnicalBiasUseCase(),
        compute_sentiment=ComputeNewsSentimentUseCase(FakeSentimentClassifier()),
        compute_macro=ComputeMacroSignalUseCase(),
        compute_combined=ComputeCombinedBiasUseCase(
            weights=BiasWeights(technical=0.4, macro=0.3, sentiment=0.3),
            thresholds=BiasThresholds(bullish=60.0, bearish=40.0),
        ),
        repository=repo,
    )

    tick = await run_tick.execute()

    assert set(tick.bias) == set(AssetSymbol)
    assert len(repo.market_snapshots) == 1
    assert len(repo.bias_reports) == len(AssetSymbol)
