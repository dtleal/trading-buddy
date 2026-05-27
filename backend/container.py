"""Composition root.

Builds every adapter from `Settings`, wires them into every use case, and
returns a `Container` of ready-to-call use cases. The CLI is the only place
that talks to the container.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from adapters.cache_redis import RedisCacheStore
from adapters.calendar_forexfactory import ForexFactoryCalendarGateway
from adapters.db_postgres import PostgresSnapshotRepository
from adapters.llm_anthropic import AnthropicLLMGateway
from adapters.macro_fedwatch import FedWatchMacroGateway
from adapters.macro_fred import FREDMacroGateway
from adapters.news_newsapi import NewsAPIGateway
from adapters.news_rss import DEFAULT_FEEDS, RSSNewsGateway
from adapters.ntfy_notifier import NtfyNotifier
from adapters.prices_yfinance import YFinancePricesGateway
from adapters.sentiment_keyword import KeywordSentimentClassifier
from core.interfaces import NewsGateway
from settings import Settings
from use_cases.compute_combined_bias import (
    BiasThresholds,
    BiasWeights,
    ComputeCombinedBiasUseCase,
)
from use_cases.compute_intraday_bias import ComputeIntradayBiasUseCase
from use_cases.compute_intraday_levels import ComputeIntradayLevelsUseCase
from use_cases.compute_macro_signal import ComputeMacroSignalUseCase
from use_cases.compute_news_sentiment import ComputeNewsSentimentUseCase
from use_cases.compute_technical_bias import ComputeTechnicalBiasUseCase
from use_cases.detect_breakout import BreakoutThresholds, DetectBreakoutsUseCase
from use_cases.detect_trade_setup import DetectTradeSetupUseCase
from use_cases.explain_event import ExplainEventUseCase
from use_cases.fetch_calendar import FetchEconomicCalendarUseCase
from use_cases.fetch_macro import FetchMacroIndicatorsUseCase
from use_cases.fetch_market import FetchMarketSnapshotUseCase
from use_cases.fetch_news import FetchNewsHeadlinesUseCase
from use_cases.generate_briefing import GenerateBriefingUseCase
from use_cases.push_breakout_alerts import PushBreakoutAlertsUseCase
from use_cases.run_dashboard_tick import RunDashboardTickUseCase

logger = logging.getLogger(__name__)


@dataclass
class Container:
    """Materialised dependency graph. Holds adapters for lifecycle management."""

    # Adapters (kept for aclose() and direct use by CLI commands like `signal`)
    cache: RedisCacheStore
    repository: PostgresSnapshotRepository
    newsapi: NewsAPIGateway
    calendar_gateway: ForexFactoryCalendarGateway
    fedwatch_gateway: FedWatchMacroGateway
    prices: YFinancePricesGateway
    ntfy: NtfyNotifier

    # Use cases (the public surface)
    run_tick: RunDashboardTickUseCase
    generate_briefing: GenerateBriefingUseCase
    explain_event: ExplainEventUseCase
    fetch_calendar: FetchEconomicCalendarUseCase
    fetch_market: FetchMarketSnapshotUseCase
    fetch_news: FetchNewsHeadlinesUseCase
    fetch_macro: FetchMacroIndicatorsUseCase

    async def aclose(self) -> None:
        for closer in (
            self.cache.close,
            self.repository.close,
            self.newsapi.close,
            self.calendar_gateway.close,
            self.fedwatch_gateway.close,
            self.ntfy.close,
        ):
            try:
                await closer()
            except Exception:  # pragma: no cover - cleanup best-effort
                logger.exception("Cleanup error in container.aclose")


def _build_news_sources(settings: Settings) -> tuple[NewsAPIGateway, list[NewsGateway]]:
    rss_sources: list[NewsGateway] = [
        RSSNewsGateway(name, url) for name, url in DEFAULT_FEEDS.items()
    ]
    api_key = settings.newsapi_key.get_secret_value() if settings.newsapi_key else None
    newsapi = NewsAPIGateway(api_key=api_key)
    all_sources: list[NewsGateway] = [*rss_sources, newsapi]
    return newsapi, all_sources


async def build_container(settings: Settings) -> Container:
    cache = RedisCacheStore(url=settings.redis_url)
    repository = PostgresSnapshotRepository(dsn=settings.postgres_dsn)

    prices = YFinancePricesGateway()
    calendar_gateway = ForexFactoryCalendarGateway()
    macro_primary = FREDMacroGateway(
        api_key=settings.fred_api_key.get_secret_value() if settings.fred_api_key else None
    )
    fedwatch = FedWatchMacroGateway()
    sentiment_classifier = KeywordSentimentClassifier()

    llm = AnthropicLLMGateway(
        api_key=settings.claude_api_key.get_secret_value(),
        default_briefing_model=settings.anthropic_model_briefing,
        default_classifier_model=settings.anthropic_model_classifier,
    )

    newsapi, news_sources = _build_news_sources(settings)

    # --- Use cases ---------------------------------------------------------

    fetch_market = FetchMarketSnapshotUseCase(prices=prices, cache=cache)
    fetch_calendar = FetchEconomicCalendarUseCase(calendar=calendar_gateway, cache=cache)
    fetch_news = FetchNewsHeadlinesUseCase(sources=news_sources)
    fetch_macro = FetchMacroIndicatorsUseCase(primary=macro_primary, fedwatch=fedwatch, cache=cache)

    compute_technical = ComputeTechnicalBiasUseCase()
    compute_sentiment = ComputeNewsSentimentUseCase(classifier=sentiment_classifier)
    compute_macro = ComputeMacroSignalUseCase()
    compute_combined = ComputeCombinedBiasUseCase(
        weights=BiasWeights(
            technical=settings.bias_weight_technical,
            macro=settings.bias_weight_macro,
            sentiment=settings.bias_weight_sentiment,
        ),
        thresholds=BiasThresholds(
            bullish=settings.bias_threshold_bullish,
            bearish=settings.bias_threshold_bearish,
        ),
    )

    compute_intraday = ComputeIntradayLevelsUseCase(
        opening_range_minutes=settings.opening_range_minutes
    )
    compute_intraday_bias = ComputeIntradayBiasUseCase()
    detect_setup = DetectTradeSetupUseCase()
    detect_breakouts = DetectBreakoutsUseCase(
        thresholds=BreakoutThresholds(
            donchian_n=settings.breakout_donchian_n,
            expansion_atr_multiple=settings.breakout_expansion_atr_multiple,
            require_squeeze=settings.breakout_require_squeeze,
        )
    )

    ntfy = NtfyNotifier(
        topic=settings.ntfy_topic.get_secret_value() if settings.ntfy_topic else None,
        server=settings.ntfy_server,
    )
    push_breakout_alerts = PushBreakoutAlertsUseCase(notifier=ntfy, cache=cache)

    run_tick = RunDashboardTickUseCase(
        fetch_market=fetch_market,
        fetch_calendar=fetch_calendar,
        fetch_news=fetch_news,
        fetch_macro=fetch_macro,
        compute_technical=compute_technical,
        compute_sentiment=compute_sentiment,
        compute_macro=compute_macro,
        compute_combined=compute_combined,
        repository=repository,
        prices=prices,
        compute_intraday=compute_intraday,
        compute_intraday_bias=compute_intraday_bias,
        detect_setup=detect_setup,
        detect_breakouts=detect_breakouts,
        push_breakout_alerts=push_breakout_alerts,
    )

    generate_briefing = GenerateBriefingUseCase(
        llm=llm,
        cache=cache,
        repository=repository,
        language=settings.output_language,
    )
    explain_event = ExplainEventUseCase(
        llm=llm,
        cache=cache,
        repository=repository,
        language=settings.output_language,
    )

    return Container(
        cache=cache,
        repository=repository,
        newsapi=newsapi,
        calendar_gateway=calendar_gateway,
        fedwatch_gateway=fedwatch,
        prices=prices,
        ntfy=ntfy,
        run_tick=run_tick,
        generate_briefing=generate_briefing,
        explain_event=explain_event,
        fetch_calendar=fetch_calendar,
        fetch_market=fetch_market,
        fetch_news=fetch_news,
        fetch_macro=fetch_macro,
    )


__all__ = ["Container", "build_container"]
