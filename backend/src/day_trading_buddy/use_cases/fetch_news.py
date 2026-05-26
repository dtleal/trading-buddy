"""Fetch recent news headlines from multiple sources, deduplicated."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from day_trading_buddy.core.interfaces import NewsGateway
from day_trading_buddy.core.models import NewsItem

logger = logging.getLogger(__name__)


class FetchNewsHeadlinesUseCase:
    """Aggregates many `NewsGateway` instances into a single deduplicated list."""

    def __init__(self, sources: Iterable[NewsGateway]) -> None:
        self._sources = list(sources)

    async def execute(
        self,
        *,
        limit_per_source: int = 25,
        max_age_minutes: int = 120,
    ) -> list[NewsItem]:
        if not self._sources:
            return []

        results = await asyncio.gather(
            *(s.fetch_recent(limit=limit_per_source) for s in self._sources),
            return_exceptions=True,
        )

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        seen_urls: set[str] = set()
        aggregated: list[NewsItem] = []

        for source_result in results:
            if isinstance(source_result, BaseException):
                logger.warning("News source raised: %s", source_result)
                continue
            for item in source_result:
                if item.url in seen_urls:
                    continue
                if item.published_at < cutoff:
                    continue
                seen_urls.add(item.url)
                aggregated.append(item)

        aggregated.sort(key=lambda i: i.published_at, reverse=True)
        return aggregated
