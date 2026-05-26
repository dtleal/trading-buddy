"""NewsAPI.org adapter (free tier: 100 requests/day).

If no API key is configured the adapter degrades to returning an empty list,
keeping the rest of the system functional.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from day_trading_buddy.core.models import NewsItem

logger = logging.getLogger(__name__)

ENDPOINT = "https://newsapi.org/v2/everything"
DEFAULT_QUERY = (
    '(Fed OR FOMC OR Powell OR "interest rate" OR CPI OR inflation OR NFP OR '
    "S&P OR Nasdaq OR gold OR VIX)"
)


class NewsAPIGateway:
    """Implements `core.interfaces.NewsGateway`."""

    source_name = "NewsAPI"

    def __init__(self, api_key: str | None, *, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=10.0)

    async def fetch_recent(self, limit: int = 50) -> list[NewsItem]:
        if not self._api_key:
            return []
        params: dict[str, Any] = {
            "q": DEFAULT_QUERY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": min(limit, 100),
            "apiKey": self._api_key,
        }
        try:
            response = await self._client.get(ENDPOINT, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("NewsAPI request failed: %s", exc)
            return []

        payload = response.json()
        articles = payload.get("articles", [])
        items: list[NewsItem] = []
        for article in articles:
            url = article.get("url")
            headline = article.get("title")
            if not url or not headline:
                continue
            published_raw = article.get("publishedAt")
            try:
                published_at = (
                    datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                    if published_raw
                    else datetime.now(timezone.utc)
                )
            except ValueError:
                published_at = datetime.now(timezone.utc)
            items.append(
                NewsItem(
                    headline=headline.strip(),
                    source=article.get("source", {}).get("name") or self.source_name,
                    url=url,
                    published_at=published_at,
                    summary=article.get("description"),
                )
            )
        return items

    async def close(self) -> None:
        await self._client.aclose()
