"""Live integration tests against real providers.

Skipped from the default suite (`make test`). Run with:

    make test-integration

- Free-tier providers (yfinance, ForexFactory, RSS) are always exercised and a
  network/parse failure is a real failure.
- Key-gated providers (FRED, NewsAPI, Anthropic) skip individually when the
  matching env var is not set.
- Infrastructure (Redis, Postgres) skips when the service is not reachable on
  the configured host/port, with a clear message pointing at `make docker-up`.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone

import pytest

from adapters.cache_redis import RedisCacheStore
from adapters.calendar_forexfactory import ForexFactoryCalendarGateway
from adapters.db_postgres import PostgresSnapshotRepository
from adapters.llm_anthropic import AnthropicLLMGateway
from adapters.macro_fred import FREDMacroGateway
from adapters.news_newsapi import NewsAPIGateway
from adapters.news_rss import DEFAULT_FEEDS, RSSNewsGateway
from adapters.prices_yfinance import YFinancePricesGateway
from core.enums import (
    AssetSymbol,
    LLMOutputKind,
    TermStructure,
    VixRegime,
)
from core.models import (
    EconomicEvent,
    MarketSnapshot,
    PriceQuote,
    VixSnapshot,
)
from settings import Settings

pytestmark = pytest.mark.integration


def _can_connect(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# -----------------------------------------------------------------------------
# Free-tier (no key) — these MUST pass; failures are real
# -----------------------------------------------------------------------------


async def test_yfinance_returns_vix_quote() -> None:
    gw = YFinancePricesGateway()
    quote = await gw.get_quote("VIX")
    assert quote.symbol == "VIX"
    assert quote.price > 0
    assert quote.timestamp.tzinfo is not None


async def test_yfinance_returns_spx_with_ma200_daily() -> None:
    gw = YFinancePricesGateway()
    quote = await gw.get_quote("SPX")
    ma200 = await gw.get_ma200("SPX", "1d")
    assert quote.price > 0
    assert ma200 is not None and ma200 > 0


async def test_yfinance_returns_ustec_quote() -> None:
    gw = YFinancePricesGateway()
    quote = await gw.get_quote("USTEC")
    assert quote.price > 0


async def test_yfinance_returns_gold_quote() -> None:
    gw = YFinancePricesGateway()
    quote = await gw.get_quote("GOLD")
    assert quote.price > 0


async def test_forexfactory_parses_weekly_feed_without_crashing() -> None:
    gw = ForexFactoryCalendarGateway()
    try:
        today = datetime.now(timezone.utc).date()
        events = await gw.get_events_for(today)
        assert isinstance(events, list)
        for event in events:
            assert isinstance(event, EconomicEvent)
            assert event.currency == "USD"
            assert event.name
    finally:
        await gw.close()


@pytest.mark.parametrize(
    "source_name,url",
    list(DEFAULT_FEEDS.items()),
    ids=list(DEFAULT_FEEDS.keys()),
)
async def test_rss_feed_returns_well_formed_headlines(source_name: str, url: str) -> None:
    gw = RSSNewsGateway(source_name=source_name, feed_url=url)
    items = await gw.fetch_recent(limit=5)
    assert isinstance(items, list)
    for item in items:
        assert item.source == source_name
        assert item.headline.strip()
        assert item.url.startswith(("http://", "https://"))
        assert item.published_at.tzinfo is not None


async def test_at_least_one_rss_feed_returns_items() -> None:
    """Soft check that the RSS aggregator can actually pull *something*. If
    every default feed is failing simultaneously we want to know."""
    total = 0
    for source_name, url in DEFAULT_FEEDS.items():
        gw = RSSNewsGateway(source_name=source_name, feed_url=url)
        total += len(await gw.fetch_recent(limit=3))
    assert total > 0, "No RSS feed returned any items — network or all feeds broken"


# -----------------------------------------------------------------------------
# Key-gated providers — skip when key missing
# -----------------------------------------------------------------------------


async def test_fred_returns_fed_funds_rate() -> None:
    key = os.getenv("FRED_API_KEY")
    if not key:
        pytest.skip("FRED_API_KEY not configured")
    gw = FREDMacroGateway(api_key=key)
    indicator = await gw.get_indicator("DFF")
    assert indicator is not None
    assert indicator.series_id == "DFF"
    assert indicator.value > 0


async def test_newsapi_returns_articles_or_empty() -> None:
    key = os.getenv("NEWSAPI_KEY")
    if not key:
        pytest.skip("NEWSAPI_KEY not configured")
    gw = NewsAPIGateway(api_key=key)
    try:
        items = await gw.fetch_recent(limit=5)
        assert isinstance(items, list)
        for item in items:
            assert item.headline.strip()
            assert item.url.startswith(("http://", "https://"))
    finally:
        await gw.close()


async def test_anthropic_haiku_responds() -> None:
    key = os.getenv("CLAUDE_API_KEY")
    if not key:
        pytest.skip("CLAUDE_API_KEY not configured")
    gw = AnthropicLLMGateway(
        api_key=key,
        default_briefing_model="claude-opus-4-7",
        default_classifier_model="claude-haiku-4-5-20251001",
    )
    # EVENT_PRE → routes to the cheap classifier model (haiku).
    output = await gw.generate(
        system_prompt="You reply with exactly one short sentence.",
        user_prompt="Say hello in English.",
        kind=LLMOutputKind.EVENT_PRE,
        max_tokens=30,
    )
    assert output.content.strip()
    assert output.kind == LLMOutputKind.EVENT_PRE
    assert output.model == "claude-haiku-4-5-20251001"


# -----------------------------------------------------------------------------
# Infrastructure — skip if service not reachable
# -----------------------------------------------------------------------------


async def test_redis_roundtrip() -> None:
    settings = Settings()
    host = os.getenv("REDIS_HOST", "localhost")
    if not _can_connect(host, settings.redis_port):
        pytest.skip(f"Redis not reachable at {host}:{settings.redis_port} — run `make docker-up`")

    cache = RedisCacheStore(url=f"redis://{host}:{settings.redis_port}/0")
    key = f"dtb:itest:{datetime.now(timezone.utc).timestamp()}"
    try:
        await cache.set(key, "ok", ttl_seconds=30)
        assert await cache.get(key) == "ok"
        await cache.delete(key)
        assert await cache.get(key) is None
    finally:
        await cache.close()


async def test_postgres_persists_market_snapshot() -> None:
    settings = Settings()
    host = os.getenv("POSTGRES_HOST", "localhost")
    if not _can_connect(host, settings.postgres_port):
        pytest.skip(
            f"Postgres not reachable at {host}:{settings.postgres_port} — run `make docker-up`"
        )

    dsn = (
        f"postgresql+asyncpg://{settings.postgres_user}:"
        f"{settings.postgres_password.get_secret_value()}@"
        f"{host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    repo = PostgresSnapshotRepository(dsn=dsn)
    try:
        now = datetime.now(timezone.utc)
        snapshot = MarketSnapshot(
            timestamp=now,
            assets={
                AssetSymbol.SPX: PriceQuote(
                    symbol="SPX", price=5900.0, timestamp=now, ma200_d=5600.0
                ),
            },
            vix=VixSnapshot(
                vix=14.0,
                vix9d=None,
                vix3m=None,
                regime=VixRegime.LOW,
                term_structure=TermStructure.FLAT,
            ),
        )
        # Requires that Alembic migrations have run against this database.
        await repo.save_market_snapshot(snapshot)
    finally:
        await repo.close()
