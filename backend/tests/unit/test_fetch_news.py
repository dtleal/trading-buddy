from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from day_trading_buddy.core.models import NewsItem
from day_trading_buddy.use_cases.fetch_news import FetchNewsHeadlinesUseCase
from tests.fakes import FakeNewsGateway


@pytest.mark.asyncio
async def test_aggregates_and_deduplicates_by_url() -> None:
    now = datetime.now(timezone.utc)
    shared = NewsItem(headline="shared", source="A", url="https://x/1", published_at=now)
    g1 = FakeNewsGateway(source_name="A", items=[shared])
    g2 = FakeNewsGateway(source_name="B", items=[shared])
    result = await FetchNewsHeadlinesUseCase([g1, g2]).execute()
    assert len(result) == 1


@pytest.mark.asyncio
async def test_drops_items_older_than_max_age() -> None:
    now = datetime.now(timezone.utc)
    fresh = NewsItem(headline="fresh", source="A", url="u1", published_at=now)
    stale = NewsItem(
        headline="stale",
        source="A",
        url="u2",
        published_at=now - timedelta(hours=3),
    )
    g = FakeNewsGateway(source_name="A", items=[fresh, stale])
    result = await FetchNewsHeadlinesUseCase([g]).execute(max_age_minutes=60)
    assert [i.url for i in result] == ["u1"]


@pytest.mark.asyncio
async def test_empty_when_no_sources_configured() -> None:
    assert await FetchNewsHeadlinesUseCase([]).execute() == []
