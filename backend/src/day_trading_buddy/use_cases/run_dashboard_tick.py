"""Top-level orchestrator. One call = one 5-minute tick.

Runs the fetch use cases in parallel, feeds their outputs into the compute use
cases, persists everything, and returns a `DashboardTick` for the renderer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from day_trading_buddy.core.interfaces import SnapshotRepository
from day_trading_buddy.core.models import DashboardTick, NewsItem
from day_trading_buddy.use_cases.compute_combined_bias import ComputeCombinedBiasUseCase
from day_trading_buddy.use_cases.compute_macro_signal import ComputeMacroSignalUseCase
from day_trading_buddy.use_cases.compute_news_sentiment import ComputeNewsSentimentUseCase
from day_trading_buddy.use_cases.compute_technical_bias import ComputeTechnicalBiasUseCase
from day_trading_buddy.use_cases.fetch_calendar import FetchEconomicCalendarUseCase
from day_trading_buddy.use_cases.fetch_macro import FetchMacroIndicatorsUseCase
from day_trading_buddy.use_cases.fetch_market import FetchMarketSnapshotUseCase
from day_trading_buddy.use_cases.fetch_news import FetchNewsHeadlinesUseCase

logger = logging.getLogger(__name__)


class RunDashboardTickUseCase:
    """Composes the full pipeline for a single tick."""

    def __init__(
        self,
        *,
        fetch_market: FetchMarketSnapshotUseCase,
        fetch_calendar: FetchEconomicCalendarUseCase,
        fetch_news: FetchNewsHeadlinesUseCase,
        fetch_macro: FetchMacroIndicatorsUseCase,
        compute_technical: ComputeTechnicalBiasUseCase,
        compute_sentiment: ComputeNewsSentimentUseCase,
        compute_macro: ComputeMacroSignalUseCase,
        compute_combined: ComputeCombinedBiasUseCase,
        repository: SnapshotRepository,
    ) -> None:
        self._fetch_market = fetch_market
        self._fetch_calendar = fetch_calendar
        self._fetch_news = fetch_news
        self._fetch_macro = fetch_macro
        self._compute_technical = compute_technical
        self._compute_sentiment = compute_sentiment
        self._compute_macro = compute_macro
        self._compute_combined = compute_combined
        self._repository = repository

    async def execute(self) -> DashboardTick:
        logger.info("Running dashboard tick")

        market, calendar_events, news, macro = await asyncio.gather(
            self._fetch_market.execute(),
            self._fetch_calendar.execute(),
            self._fetch_news.execute(),
            self._fetch_macro.execute(),
        )

        # Run the three sub-score computations concurrently. They are pure.
        technical, sentiment_by_asset, macro_by_asset = await asyncio.gather(
            self._compute_technical.execute(market),
            self._compute_sentiment.execute(news),
            self._compute_macro.execute(macro),
        )

        bias = await self._compute_combined.execute(
            technical=technical,
            macro=macro_by_asset,
            sentiment=sentiment_by_asset,
        )

        tick = DashboardTick(
            timestamp=datetime.now(timezone.utc),
            market=market,
            macro=macro,
            events_today=calendar_events,
            recent_news=news,
            bias=bias,
        )

        await asyncio.gather(
            self._repository.save_market_snapshot(market),
            self._repository.save_events(calendar_events),
            self._repository.save_news(_with_neutral_default(news)),
            self._repository.save_bias_reports(list(bias.values())),
        )

        return tick


def _with_neutral_default(items: list[NewsItem]) -> list[NewsItem]:
    """Sentiment is computed at aggregate level for now; rows still need labels
    optional. Returns the list unchanged — kept as a hook for future per-item
    classification."""
    return items
