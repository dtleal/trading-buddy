from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from core.enums import TRACKED_ASSETS, AssetSymbol
from core.models import IntradayBar, PriceQuote
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
from use_cases.compute_intraday_levels import ComputeIntradayLevelsUseCase
from use_cases.compute_macro_signal import ComputeMacroSignalUseCase
from use_cases.compute_news_sentiment import ComputeNewsSentimentUseCase
from use_cases.compute_technical_bias import ComputeTechnicalBiasUseCase
from use_cases.detect_trade_setup import DetectTradeSetupUseCase
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

    assert set(tick.bias) == set(TRACKED_ASSETS)
    assert len(repo.market_snapshots) == 1
    assert len(repo.bias_reports) == len(TRACKED_ASSETS)


@dataclass
class _RecordingPrices(FakePricesGateway):
    """FakePricesGateway that logs which symbols asked Yahoo for 5m bars."""

    intraday_calls: list[str] = field(default_factory=list)

    async def get_intraday_bars(
        self, symbol: str, interval: str, lookback_days: int
    ) -> list[IntradayBar]:
        self.intraday_calls.append(symbol)
        return []


def _m5_bars(count: int, price: float) -> list[IntradayBar]:
    """`count` M5 bars ending now, with the tick volume MT5 reports."""
    start = datetime.now(timezone.utc) - timedelta(minutes=5 * count)
    bars: list[IntradayBar] = []
    for i in range(count):
        close = price + (i % 10) * price * 0.0001
        bars.append(
            IntradayBar(
                timestamp=start + timedelta(minutes=5 * i),
                open=close,
                high=close * 1.0002,
                low=close * 0.9998,
                close=close,
                volume=120.0,
            )
        )
    return bars


@pytest.mark.asyncio
async def test_intraday_levels_prefer_mt5_bars_over_yahoo() -> None:
    """MT5 bars win when the collector has history, and they carry tick volume,
    so VWAP exists on EURUSD — Yahoo reports zero volume for FX."""
    now = datetime.now(timezone.utc)
    cache = InMemoryCache()
    prices = _RecordingPrices(
        quotes={"EURUSD": PriceQuote(symbol="EURUSD", price=1.16, timestamp=now)}
    )

    run_tick = RunDashboardTickUseCase(
        fetch_market=FetchMarketSnapshotUseCase(prices=prices, cache=cache),
        fetch_calendar=FetchEconomicCalendarUseCase(calendar=FakeCalendarGateway(), cache=cache),
        fetch_news=FetchNewsHeadlinesUseCase([FakeNewsGateway()]),
        fetch_macro=FetchMacroIndicatorsUseCase(
            primary=FakeMacroGateway(), fedwatch=FakeMacroGateway(), cache=cache
        ),
        compute_technical=ComputeTechnicalBiasUseCase(),
        compute_sentiment=ComputeNewsSentimentUseCase(FakeSentimentClassifier()),
        compute_macro=ComputeMacroSignalUseCase(),
        compute_combined=ComputeCombinedBiasUseCase(
            weights=BiasWeights(technical=0.4, macro=0.3, sentiment=0.3),
            thresholds=BiasThresholds(bullish=60.0, bearish=40.0),
        ),
        repository=FakeSnapshotRepository(),
        prices=prices,
        compute_intraday=ComputeIntradayLevelsUseCase(),
        detect_setup=DetectTradeSetupUseCase(),
        bars_provider=lambda: {AssetSymbol.EURUSD: _m5_bars(500, 1.16)},
    )

    tick = await run_tick.execute()

    levels = tick.intraday_levels[AssetSymbol.EURUSD]
    assert levels.vwap is not None
    assert levels.last_price == pytest.approx(1.16, rel=1e-3)
    # EURUSD never touched Yahoo; the assets without MT5 bars still fall back.
    assert "EURUSD" not in prices.intraday_calls
    assert "USTEC" in prices.intraday_calls
