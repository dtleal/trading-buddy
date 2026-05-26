"""RSS news aggregator. One instance per source — many instances are combined upstream."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser

from day_trading_buddy.core.models import NewsItem

logger = logging.getLogger(__name__)

# Free RSS feeds known to publish market-moving headlines.
DEFAULT_FEEDS: dict[str, str] = {
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "CNBC Markets": "https://www.cnbc.com/id/15839069/device/rss/rss.html",
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
    "Federal Reserve": "https://www.federalreserve.gov/feeds/press_all.xml",
}


def _parse_date(entry: dict[str, Any]) -> datetime:
    """Best-effort published_at parse from a feedparser entry."""
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if not value:
            continue
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (TypeError, ValueError):
            continue
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(
            parsed[0],
            parsed[1],
            parsed[2],
            parsed[3],
            parsed[4],
            parsed[5],
            tzinfo=timezone.utc,
        )
    return datetime.now(timezone.utc)


class RSSNewsGateway:
    """A single RSS source. Implements `core.interfaces.NewsGateway`."""

    def __init__(self, source_name: str, feed_url: str) -> None:
        self.source_name = source_name
        self._feed_url = feed_url

    def _fetch_sync(self, limit: int) -> list[NewsItem]:
        parsed = feedparser.parse(self._feed_url)
        items: list[NewsItem] = []
        for entry in parsed.entries[:limit]:
            headline = entry.get("title")
            link = entry.get("link")
            if not headline or not link:
                continue
            items.append(
                NewsItem(
                    headline=str(headline).strip(),
                    source=self.source_name,
                    url=str(link),
                    published_at=_parse_date(entry),
                    summary=(entry.get("summary") or None),
                )
            )
        return items

    async def fetch_recent(self, limit: int = 50) -> list[NewsItem]:
        try:
            return await asyncio.to_thread(self._fetch_sync, limit)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("RSS fetch failed for %s: %s", self.source_name, exc)
            return []
