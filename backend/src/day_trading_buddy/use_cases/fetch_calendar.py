"""Fetch today's high-impact USD economic events."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from day_trading_buddy.core.enums import ImpactLevel
from day_trading_buddy.core.interfaces import CacheStore, CalendarGateway
from day_trading_buddy.core.models import EconomicEvent

logger = logging.getLogger(__name__)

CACHE_KEY = "calendar:today"
CACHE_TTL_SECONDS = 3600  # 1 hour — calendar barely changes intraday


class FetchEconomicCalendarUseCase:
    """Returns today's events ordered by scheduled time."""

    def __init__(self, calendar: CalendarGateway, cache: CacheStore) -> None:
        self._calendar = calendar
        self._cache = cache

    async def execute(
        self,
        *,
        day: date | None = None,
        min_impact: ImpactLevel = ImpactLevel.MEDIUM,
    ) -> list[EconomicEvent]:
        target_day = day or datetime.now(timezone.utc).date()
        cache_key = f"{CACHE_KEY}:{target_day.isoformat()}:{min_impact.value}"

        cached = await self._cache.get(cache_key)
        if cached:
            try:
                payload = json.loads(cached)
                return [EconomicEvent.model_validate(item) for item in payload]
            except Exception:
                logger.debug("Stale calendar cache; refetching")

        events = await self._calendar.get_events_for(target_day)
        filtered = sorted(
            (e for e in events if _impact_at_least(e.impact, min_impact)),
            key=lambda e: e.scheduled_at,
        )

        await self._cache.set(
            cache_key,
            json.dumps([e.model_dump(mode="json") for e in filtered]),
            ttl_seconds=CACHE_TTL_SECONDS,
        )
        return filtered


def _impact_at_least(actual: ImpactLevel, minimum: ImpactLevel) -> bool:
    order = {ImpactLevel.LOW: 0, ImpactLevel.MEDIUM: 1, ImpactLevel.HIGH: 2}
    return order[actual] >= order[minimum]
