"""Top-level orchestrator. One call = one 5-minute tick.

Runs the fetch use cases in parallel, feeds their outputs into the compute use
cases, persists everything, and returns a `DashboardTick` for the renderer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from adapters.prices_yfinance import YFinancePricesGateway
from core.enums import AssetSymbol, Timeframe
from core.interfaces import SnapshotRepository
from core.models import (
    BiasReport,
    Breakout,
    DashboardTick,
    IntradayLevels,
    NewsItem,
    TradeSetup,
)
from use_cases.compute_combined_bias import ComputeCombinedBiasUseCase
from use_cases.compute_intraday_levels import ComputeIntradayLevelsUseCase
from use_cases.compute_macro_signal import ComputeMacroSignalUseCase
from use_cases.compute_news_sentiment import ComputeNewsSentimentUseCase
from use_cases.compute_technical_bias import ComputeTechnicalBiasUseCase
from use_cases.detect_breakout import DetectBreakoutsUseCase
from use_cases.detect_trade_setup import DetectTradeSetupUseCase
from use_cases.fetch_calendar import FetchEconomicCalendarUseCase
from use_cases.fetch_macro import FetchMacroIndicatorsUseCase
from use_cases.fetch_market import FetchMarketSnapshotUseCase
from use_cases.fetch_news import FetchNewsHeadlinesUseCase
from use_cases.push_breakout_alerts import PushBreakoutAlertsUseCase
from use_cases.resample_bars import resample_to

# Timeframes the dashboard surfaces for breakout alerts.
# M5 is enabled by request: the trader operates on the 5-minute chart and wants
# notifications for fresh breakouts at that timeframe. Squeeze + 1.3×ATR
# expansion + fresh-cross filters already kill most 5m noise.
BREAKOUT_TIMEFRAMES: tuple[Timeframe, ...] = (
    Timeframe.M5,
    Timeframe.M15,
    Timeframe.M30,
    Timeframe.H1,
    Timeframe.H4,
)

# Lookback days for the 5m fetch. 4h breakouts need at least 20 closed 4h bars
# (N=20 in the Donchian) + ATR window + room for the scan. 15 days of RTH is
# comfortably enough for indices; futures (GC=F, 23h) get even more bars.
BREAKOUT_LOOKBACK_DAYS = 15

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
        detect_breakouts: DetectBreakoutsUseCase | None = None,
        push_breakout_alerts: PushBreakoutAlertsUseCase | None = None,
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
        self._detect_breakouts = detect_breakouts
        self._push_breakout_alerts = push_breakout_alerts
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

        intraday_levels, setups, breakouts = await self._compute_intraday_setups_breakouts(bias)

        # Push new breakouts to the user's phone via ntfy.sh (no-op if not
        # configured). Done before building the tick so the user gets the
        # alert as soon as the data is detected.
        if self._push_breakout_alerts is not None and breakouts:
            try:
                await self._push_breakout_alerts.execute(breakouts)
            except Exception:
                logger.exception("Push notification dispatch failed (tick continues)")

        tick = DashboardTick(
            timestamp=datetime.now(timezone.utc),
            market=market,
            macro=macro,
            events_today=calendar_events,
            recent_news=news,
            bias=bias,
            setups=setups,
            intraday_levels=intraday_levels,
            breakouts_recent=breakouts,
        )

        await asyncio.gather(
            self._repository.save_market_snapshot(market),
            self._repository.save_events(calendar_events),
            self._repository.save_news(_with_neutral_default(news)),
            self._repository.save_bias_reports(list(bias.values())),
        )

        return tick

    async def _compute_intraday_setups_breakouts(
        self,
        bias: dict[AssetSymbol, BiasReport],
    ) -> tuple[dict[AssetSymbol, IntradayLevels], list[TradeSetup], list[Breakout]]:
        """Best-effort: pull 5m bars per asset, compute intraday levels, trade
        setups, and breakout signals across all configured timeframes.

        Failures on a single asset (rate limit, missing bars) are logged but
        do not break the tick — the dashboard simply omits that asset's data.
        """
        prices = self._prices
        compute_intraday = self._compute_intraday
        detect_setup = self._detect_setup
        detect_breakouts = self._detect_breakouts
        if prices is None or compute_intraday is None or detect_setup is None:
            return {}, [], []

        async def _one(
            asset: AssetSymbol,
        ) -> tuple[AssetSymbol, IntradayLevels | None, TradeSetup | None, list[Breakout]]:
            try:
                bars = await prices.get_intraday_bars(asset.value, "5m", BREAKOUT_LOOKBACK_DAYS)
                levels = compute_intraday.execute(asset.value, bars)
                setup = None
                if levels is not None:
                    setup = detect_setup.execute(levels, bias[asset])
                # Breakout detection across configured timeframes.
                asset_breakouts: list[Breakout] = []
                if detect_breakouts is not None and bars:
                    for tf in BREAKOUT_TIMEFRAMES:
                        tf_bars = resample_to(bars, tf)
                        asset_breakouts.extend(detect_breakouts.execute(asset, tf, tf_bars))
                return asset, levels, setup, asset_breakouts
            except Exception:
                logger.exception("Intraday/setup/breakout failed for %s", asset.value)
                return asset, None, None, []

        results = await asyncio.gather(*(_one(a) for a in self._intraday_assets))
        levels_map: dict[AssetSymbol, IntradayLevels] = {}
        setups: list[TradeSetup] = []
        breakouts: list[Breakout] = []
        for asset, lv, sp, bk in results:
            if lv is not None:
                levels_map[asset] = lv
            if sp is not None:
                setups.append(sp)
            breakouts.extend(bk)
        # Most recent first — frontend slices for display.
        breakouts.sort(key=lambda b: b.signal_bar_at, reverse=True)
        return levels_map, setups, breakouts


def _with_neutral_default(items: list[NewsItem]) -> list[NewsItem]:
    """Sentiment is computed at aggregate level for now; rows still need labels
    optional. Returns the list unchanged — kept as a hook for future per-item
    classification."""
    return items
