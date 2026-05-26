"""ForexFactory weekly XML calendar adapter.

Filters to USD events only (these dominate USTEC/SPX/Gold). High/medium/low
impact is preserved on the model so callers can filter as they wish.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from core.enums import ImpactLevel
from core.models import EconomicEvent

logger = logging.getLogger(__name__)

WEEKLY_XML_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

IMPACT_MAP: dict[str, ImpactLevel] = {
    "high": ImpactLevel.HIGH,
    "medium": ImpactLevel.MEDIUM,
    "low": ImpactLevel.LOW,
    "holiday": ImpactLevel.LOW,
}


def _parse_event_datetime(date_str: str, time_str: str) -> datetime | None:
    """ForexFactory uses MM-DD-YYYY / 'h:mma' US Eastern. We treat as UTC-naive then UTC."""
    if not date_str or not time_str or time_str.lower() in ("all day", "tentative"):
        return None
    try:
        combined = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
    except ValueError:
        return None
    # XML feed publishes Eastern Time without TZ. Approximate as UTC-5 (EST).
    return (combined + timedelta(hours=5)).replace(tzinfo=timezone.utc)


class ForexFactoryCalendarGateway:
    """Implements `core.interfaces.CalendarGateway`."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=15.0, follow_redirects=True)

    async def get_events_for(self, day: date) -> list[EconomicEvent]:
        try:
            response = await self._client.get(WEEKLY_XML_URL)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("ForexFactory fetch failed: %s", exc)
            return []

        soup = BeautifulSoup(response.content, "xml")
        events: list[EconomicEvent] = []
        for event_node in soup.find_all("event"):
            currency = event_node.find("country") or event_node.find("currency")
            if currency is None or currency.text.strip().upper() != "USD":
                continue
            title = event_node.find("title")
            date_node = event_node.find("date")
            time_node = event_node.find("time")
            impact_node = event_node.find("impact")
            forecast_node = event_node.find("forecast")
            previous_node = event_node.find("previous")
            actual_node = event_node.find("actual")
            if not (title and date_node and time_node and impact_node):
                continue

            scheduled = _parse_event_datetime(date_node.text.strip(), time_node.text.strip())
            if scheduled is None or scheduled.date() != day:
                continue

            impact = IMPACT_MAP.get(impact_node.text.strip().lower(), ImpactLevel.LOW)
            events.append(
                EconomicEvent(
                    name=title.text.strip(),
                    currency="USD",
                    impact=impact,
                    scheduled_at=scheduled,
                    forecast=forecast_node.text.strip() if forecast_node else None,
                    previous=previous_node.text.strip() if previous_node else None,
                    actual=actual_node.text.strip() if actual_node and actual_node.text else None,
                )
            )
        return events

    async def close(self) -> None:
        await self._client.aclose()
