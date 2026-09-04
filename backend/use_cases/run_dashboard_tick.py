"""Top-level orchestrator. One call = one 5-minute tick.

Runs the fetch use cases in parallel, feeds their outputs into the compute use
cases, persists everything, and returns a `DashboardTick` for the renderer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Callable

from adapters.prices_yfinance import YFinancePricesGateway
from core.enums import TRACKED_ASSETS, AssetSymbol, Timeframe
from core.interfaces import SnapshotRepository
from core.models import (
    BiasReport,
    Breakout,
    DashboardTick,
    DayOutlook,
    IntradayBar,
    IntradayBiasReport,
    IntradayLevels,
    MarketSnapshot,
    NewsItem,
    SessionLiquidity,
    TradeSetup,
    VixPriceSignal,
)
from use_cases.assess_day_outlook import AssessDayOutlookUseCase
from use_cases.assess_vix_price import AssessVixPriceUseCase
from use_cases.compute_combined_bias import ComputeCombinedBiasUseCase
from use_cases.compute_intraday_bias import ComputeIntradayBiasUseCase
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
from use_cases.push_day_outlook_alerts import PushDayOutlookAlertsUseCase
from use_cases.push_vix_price_alerts import PushVixPriceAlertsUseCase
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

# Fewest MT5 bars we trust instead of yfinance. 400 M5 bars ≈ 1.4 days of a
# 24h instrument: enough for EMA200/SMA200 and for a previous-day session to
# exist. Below that the collector is down or still backfilling its deep history,
# so the tick falls back to Yahoo rather than publishing half-formed levels.
MIN_MT5_BARS = 400

# Lookback for the VIX 5m bars feeding the VIX×price stance. Two sessions give
# the trend window plus a meaningful "position in recent range" read without
# dragging in week-old vol levels.
VIX_PRICE_LOOKBACK_DAYS = 2

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
        compute_intraday_bias: ComputeIntradayBiasUseCase | None = None,
        detect_setup: DetectTradeSetupUseCase | None = None,
        detect_breakouts: DetectBreakoutsUseCase | None = None,
        push_breakout_alerts: PushBreakoutAlertsUseCase | None = None,
        assess_day_outlook: AssessDayOutlookUseCase | None = None,
        push_day_outlook_alerts: PushDayOutlookAlertsUseCase | None = None,
        assess_vix_price: AssessVixPriceUseCase | None = None,
        push_vix_price_alerts: PushVixPriceAlertsUseCase | None = None,
        liquidity_provider: Callable[[], dict[AssetSymbol, SessionLiquidity]] | None = None,
        bars_provider: Callable[[], dict[AssetSymbol, list[IntradayBar]]] | None = None,
        intraday_assets: tuple[AssetSymbol, ...] = TRACKED_ASSETS,
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
        self._compute_intraday_bias = compute_intraday_bias
        self._detect_setup = detect_setup
        self._detect_breakouts = detect_breakouts
        self._push_breakout_alerts = push_breakout_alerts
        self._assess_day_outlook = assess_day_outlook
        self._push_day_outlook_alerts = push_day_outlook_alerts
        self._assess_vix_price = assess_vix_price
        self._push_vix_price_alerts = push_vix_price_alerts
        self._liquidity_provider = liquidity_provider
        # M5 bars straight from MT5 (the collector). Preferred over yfinance —
        # see `MIN_MT5_BARS` and `_compute_intraday_setups_breakouts`.
        self._bars_provider = bars_provider
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

        (
            intraday_levels,
            setups,
            breakouts,
            bars_by_asset,
        ) = await self._compute_intraday_setups_breakouts(bias)

        # Per-asset intraday bias is derived from the same intraday levels —
        # no extra API calls. Built here (vs inside the gather helper) so the
        # helper signature stays tight and this stays trivially testable.
        intraday_bias_map: dict[AssetSymbol, IntradayBiasReport] = {}
        if self._compute_intraday_bias is not None:
            for asset, levels in intraday_levels.items():
                intraday_bias_map[asset] = self._compute_intraday_bias.execute(asset, levels)

        # Push new breakouts to the user's phone via ntfy.sh (no-op if not
        # configured). Done before building the tick so the user gets the
        # alert as soon as the data is detected.
        if self._push_breakout_alerts is not None and breakouts:
            try:
                await self._push_breakout_alerts.execute(breakouts)
            except Exception:
                logger.exception("Push notification dispatch failed (tick continues)")

        # Day-outlook gate: combine the structural signals just computed with
        # the live MT5 liquidity readings (if a collector is feeding them).
        day_outlook = self._assess_outlook(market, calendar_events, intraday_levels)
        if day_outlook is not None and self._push_day_outlook_alerts is not None:
            try:
                await self._push_day_outlook_alerts.execute(day_outlook)
            except Exception:
                logger.exception("Day-outlook push dispatch failed (tick continues)")

        # VIX×price stance: reuse the 5m bars already fetched above, pull the
        # VIX's own 5m path, and correlate them into a per-asset playbook.
        vix_price = await self._assess_vix_price_signals(market, bars_by_asset)
        if vix_price and self._push_vix_price_alerts is not None:
            try:
                await self._push_vix_price_alerts.execute(vix_price)
            except Exception:
                logger.exception("VIX×price push dispatch failed (tick continues)")

        tick = DashboardTick(
            timestamp=datetime.now(timezone.utc),
            market=market,
            macro=macro,
            events_today=calendar_events,
            recent_news=news,
            bias=bias,
            setups=setups,
            intraday_levels=intraday_levels,
            intraday_bias=intraday_bias_map,
            breakouts_recent=breakouts,
            day_outlook=day_outlook,
            vix_price=vix_price,
        )

        await asyncio.gather(
            self._repository.save_market_snapshot(market),
            self._repository.save_events(calendar_events),
            self._repository.save_news(_with_neutral_default(news)),
            self._repository.save_bias_reports(list(bias.values())),
        )

        return tick

    def _assess_outlook(
        self,
        market,
        calendar_events,
        intraday_levels: dict[AssetSymbol, IntradayLevels],
    ) -> DayOutlook | None:
        """Run the day-outlook gate. Returns None when the assessor isn't wired
        (older tests) so the tick stays backward-compatible."""
        if self._assess_day_outlook is None:
            return None
        liquidity = self._liquidity_provider() if self._liquidity_provider else {}
        try:
            return self._assess_day_outlook.execute(
                now=datetime.now(timezone.utc),
                events_today=calendar_events,
                vix=market.vix,
                levels=intraday_levels,
                liquidity=liquidity,
            )
        except Exception:
            logger.exception("Day-outlook assessment failed (tick continues)")
            return None

    async def _assess_vix_price_signals(
        self,
        market: MarketSnapshot,
        bars_by_asset: dict[AssetSymbol, list[IntradayBar]],
    ) -> dict[AssetSymbol, VixPriceSignal]:
        """Fetch the VIX 5m path and run the VIX×price stance matrix.

        Best-effort like everything else in the tick: any failure (yfinance
        throttle, market closed) logs and yields an empty map."""
        if self._assess_vix_price is None or self._prices is None or not bars_by_asset:
            return {}
        try:
            vix_bars = await self._prices.get_intraday_bars("VIX", "5m", VIX_PRICE_LOOKBACK_DAYS)
        except Exception:
            logger.exception("VIX 5m bars fetch failed (tick continues)")
            return {}
        try:
            return self._assess_vix_price.execute(
                now=datetime.now(timezone.utc),
                vix=market.vix,
                vix_bars=vix_bars,
                bars_by_asset=_aligned_to_vix(bars_by_asset, vix_bars),
            )
        except Exception:
            logger.exception("VIX×price assessment failed (tick continues)")
            return {}

    async def _compute_intraday_setups_breakouts(
        self,
        bias: dict[AssetSymbol, BiasReport],
    ) -> tuple[
        dict[AssetSymbol, IntradayLevels],
        list[TradeSetup],
        list[Breakout],
        dict[AssetSymbol, list[IntradayBar]],
    ]:
        """Best-effort: read 5m bars per asset, compute intraday levels, trade
        setups, and breakout signals across all configured timeframes. The raw
        5m bars are also returned so downstream reads (VIX×price stance) reuse
        them without fetching twice.

        Bars come from MT5 (the collector) whenever it has enough history —
        broker's own prices, real tick volume, no delay. Yahoo is the fallback
        for when the collector is down.

        Failures on a single asset (rate limit, missing bars) are logged but
        do not break the tick — the dashboard simply omits that asset's data.
        """
        prices = self._prices
        mt5_bars = self._bars_provider() if self._bars_provider is not None else {}
        compute_intraday = self._compute_intraday
        detect_setup = self._detect_setup
        detect_breakouts = self._detect_breakouts
        if prices is None or compute_intraday is None or detect_setup is None:
            return {}, [], [], {}

        async def _one(
            asset: AssetSymbol,
        ) -> tuple[
            AssetSymbol,
            IntradayLevels | None,
            TradeSetup | None,
            list[Breakout],
            list[IntradayBar],
        ]:
            try:
                bars: Sequence[IntradayBar] = mt5_bars.get(asset, [])
                if len(bars) < MIN_MT5_BARS:
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
                return asset, levels, setup, asset_breakouts, list(bars)
            except Exception:
                logger.exception("Intraday/setup/breakout failed for %s", asset.value)
                return asset, None, None, [], []

        results = await asyncio.gather(*(_one(a) for a in self._intraday_assets))
        levels_map: dict[AssetSymbol, IntradayLevels] = {}
        setups: list[TradeSetup] = []
        breakouts: list[Breakout] = []
        bars_map: dict[AssetSymbol, list[IntradayBar]] = {}
        for asset, lv, sp, bk, bars in results:
            if lv is not None:
                levels_map[asset] = lv
            if sp is not None:
                setups.append(sp)
            breakouts.extend(bk)
            if bars:
                bars_map[asset] = bars
        # Most recent first — frontend slices for display.
        breakouts.sort(key=lambda b: b.signal_bar_at, reverse=True)
        return levels_map, setups, breakouts, bars_map


def _aligned_to_vix(
    bars_by_asset: dict[AssetSymbol, list[IntradayBar]],
    vix_bars: Sequence[IntradayBar],
) -> dict[AssetSymbol, list[IntradayBar]]:
    """Cut the price bars off where the VIX bars end.

    The stance compares a VIX state with a price state, so both sides have to
    describe the same clock time. The price bars now come from MT5 and are live,
    while the VIX only exists on Yahoo (no broker symbol for it) and runs ~15
    minutes late — comparing them raw would read "price falling, VIX flat" purely
    from the lag. Dropping the price bars newer than the last VIX bar costs three
    bars of freshness and keeps the comparison honest.
    """
    if not vix_bars:
        return bars_by_asset
    cutoff = vix_bars[-1].timestamp
    aligned: dict[AssetSymbol, list[IntradayBar]] = {}
    for asset, bars in bars_by_asset.items():
        trimmed = [b for b in bars if b.timestamp <= cutoff]
        aligned[asset] = trimmed or bars
    return aligned


def _with_neutral_default(items: list[NewsItem]) -> list[NewsItem]:
    """Sentiment is computed at aggregate level for now; rows still need labels
    optional. Returns the list unchanged — kept as a hook for future per-item
    classification."""
    return items
