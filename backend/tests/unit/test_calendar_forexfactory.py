"""Unit tests for the ForexFactory time parser.

Locks the behavior verified against real public feed entries:
- CB Consumer Confidence (10:00 AM ET) → "2:00pm" in feed → 14:00 UTC
- Prelim GDP (8:30 AM ET)             → "12:30pm" in feed → 12:30 UTC

If we ever regress to "+5h offset" again, these tests will fail loud.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from adapters.calendar_forexfactory import ForexFactoryCalendarGateway, _parse_event_datetime
from core.enums import ImpactLevel


def test_parses_pm_time_as_utc() -> None:
    # CB Consumer Confidence (10:00 AM ET in EDT == 14:00 UTC)
    parsed = _parse_event_datetime("05-26-2026", "2:00pm")
    assert parsed == datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc)


def test_parses_am_time_as_utc() -> None:
    parsed = _parse_event_datetime("05-28-2026", "12:30pm")
    assert parsed == datetime(2026, 5, 28, 12, 30, tzinfo=timezone.utc)


def test_parses_midnight_as_utc() -> None:
    parsed = _parse_event_datetime("05-28-2026", "12:00am")
    assert parsed == datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc)


def test_returns_none_for_all_day() -> None:
    assert _parse_event_datetime("05-26-2026", "All Day") is None


def test_returns_none_for_tentative() -> None:
    assert _parse_event_datetime("05-26-2026", "Tentative") is None


def test_returns_none_for_empty() -> None:
    assert _parse_event_datetime("", "") is None
    assert _parse_event_datetime("05-26-2026", "") is None


def test_returns_none_for_malformed_time() -> None:
    assert _parse_event_datetime("05-26-2026", "25:99xx") is None


_HOLIDAY_XML = b"""<?xml version="1.0"?>
<weeklyevents>
  <event>
    <title>Bank Holiday</title>
    <country>USD</country>
    <date><![CDATA[06-19-2026]]></date>
    <time><![CDATA[All Day]]></time>
    <impact><![CDATA[Holiday]]></impact>
  </event>
</weeklyevents>
"""


@pytest.mark.asyncio
async def test_holiday_mapped_to_holiday_tier_with_all_day_fallback() -> None:
    """A US bank holiday published as 'All Day' must surface as a HOLIDAY-tier
    event anchored to the feed date (not dropped, not squashed to LOW)."""
    from datetime import date

    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=_HOLIDAY_XML))
    client = httpx.AsyncClient(transport=transport)
    gw = ForexFactoryCalendarGateway(client=client)

    events = await gw.get_events_for(date(2026, 6, 19))
    await gw.close()

    assert len(events) == 1
    assert events[0].impact is ImpactLevel.HOLIDAY
    assert events[0].scheduled_at.date() == date(2026, 6, 19)
