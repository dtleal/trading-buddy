"""ForexFactory weekly XML calendar adapter.

Filters to USD events only (these dominate USTEC/SPX/Gold). High/medium/low
impact is preserved on the model so callers can filter as they wish.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

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
    """Parse the ForexFactory weekly feed timestamp.

    Format: MM-DD-YYYY / 'h:mma'. Despite older comments suggesting otherwise,
    the public XML feed (`ff_calendar_thisweek.xml`) publishes times in **UTC**,
    not Eastern Time. Verified against well-known US releases — e.g.
    CB Consumer Confidence (10:00 AM ET) appears as "2:00pm" = 14:00 UTC, and
    Prelim GDP (8:30 AM ET) appears as "12:30pm" = 12:30 UTC. Both match UTC,
    not ET. Previously the adapter wrongly added 5 hours, putting every US
    event 5h in the future.
    """
    if not date_str or not time_str or time_str.lower() in ("all day", "tentative"):
        return None
    try:
        combined = datetime.strptime(f"{date_str} {time_str}", "%m-%d-%Y %I:%M%p")
    except ValueError:
        return None
    return combined.replace(tzinfo=timezone.utc)


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

        # Detect the rate-limit HTML page — ForexFactory returns it with HTTP 200
        # but the body is an HTML page, not the XML feed. Without this check, the
        # XML parser silently sees zero <event> nodes and we look like we have a
        # quiet calendar day.
        content = response.content
        if b"<event>" not in content:
            preview = content[:200].decode("utf-8", errors="replace")
            logger.warning(
                "ForexFactory returned no <event> nodes (status=%s). Likely rate "
                "limit or feed shape change. Body preview: %r",
                response.status_code,
                preview,
            )
            return []

        soup = BeautifulSoup(content, "xml")
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
