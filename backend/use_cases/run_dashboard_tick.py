"""Top-level orchestrator. One call = one 5-minute tick.

Runs the fetch use cases in parallel, feeds their outputs into the compute use
cases, persists everything, and returns a `DashboardTick` for the renderer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from adapters.prices_yfinance import YFinancePricesGateway
from core.enums import AssetSymbol
from core.interfaces import SnapshotRepository
from core.models import BiasReport, DashboardTick, IntradayLevels, NewsItem, TradeSetup
from use_cases.compute_combined_bias import ComputeCombinedBiasUseCase
from use_cases.compute_intraday_levels import ComputeIntradayLevelsUseCase
from use_cases.compute_macro_signal import ComputeMacroSignalUseCase
from use_cases.compute_news_sentiment import ComputeNewsSentimentUseCase
from use_cases.compute_technical_bias import ComputeTechnicalBiasUseCase
from use_cases.detect_trade_setup import DetectTradeSetupUseCase
from use_cases.fetch_calendar import FetchEconomicCalendarUseCase
from use_cases.fetch_macro import FetchMacroIndicatorsUseCase
from use_cases.fetch_market import FetchMarketSnapshotUseCase
from use_cases.fetch_news import FetchNewsHeadlinesUseCase

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
        prices: YFinancePricesGateway | None = None,
        compute_intraday: ComputeIntradayLevelsUseCase | None = None,
        detect_setup: DetectTradeSetupUseCase | None = None,
        intraday_assets: tuple[AssetSymbol, ...] = (
            AssetSymbol.USTEC,
            AssetSymbol.SPX,
            AssetSymbol.GOLD,
        ),
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
        # Optional intraday pipeline. Old tests can still wire this UC without
        # passing these, in which case setups will simply be an empty list.
        self._prices = prices
        self._compute_intraday = compute_intraday
        self._detect_setup = detect_setup
        self._intraday_assets = intraday_assets

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

        intraday_levels, setups = await self._compute_intraday_and_setups(bias)

        tick = DashboardTick(
            timestamp=datetime.now(timezone.utc),
            market=market,
            macro=macro,
            events_today=calendar_events,
            recent_news=news,
            bias=bias,
            setups=setups,
            intraday_levels=intraday_levels,
        )

        await asyncio.gather(
            self._repository.save_market_snapshot(market),
            self._repository.save_events(calendar_events),
            self._repository.save_news(_with_neutral_default(news)),
            self._repository.save_bias_reports(list(bias.values())),
        )

        return tick

    async def _compute_intraday_and_setups(
        self,
        bias: dict[AssetSymbol, BiasReport],
    ) -> tuple[dict[AssetSymbol, IntradayLevels], list[TradeSetup]]:
        """Best-effort: pull 5m bars for each asset, compute levels + setups.

        Failures on a single asset (rate limit, missing bars) are logged but
        do not break the tick — the dashboard simply omits that asset's
        intraday line and its setup.
        """
        prices = self._prices
        compute_intraday = self._compute_intraday
        detect_setup = self._detect_setup
        if prices is None or compute_intraday is None or detect_setup is None:
            return {}, []

        async def _one(
            asset: AssetSymbol,
        ) -> tuple[AssetSymbol, IntradayLevels | None, TradeSetup | None]:
            try:
                bars = await prices.get_intraday_bars(asset.value, "5m", 5)
                levels = compute_intraday.execute(asset.value, bars)
                if levels is None:
                    return asset, None, None
                setup = detect_setup.execute(levels, bias[asset])
                return asset, levels, setup
            except Exception:
                logger.exception("Intraday/setup failed for %s", asset.value)
                return asset, None, None

        results = await asyncio.gather(*(_one(a) for a in self._intraday_assets))
        levels_map: dict[AssetSymbol, IntradayLevels] = {}
        setups: list[TradeSetup] = []
        for asset, lv, sp in results:
            if lv is not None:
                levels_map[asset] = lv
            if sp is not None:
                setups.append(sp)
        return levels_map, setups


def _with_neutral_default(items: list[NewsItem]) -> list[NewsItem]:
    """Sentiment is computed at aggregate level for now; rows still need labels
    optional. Returns the list unchanged — kept as a hook for future per-item
    classification."""
    return items
