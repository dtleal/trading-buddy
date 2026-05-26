from __future__ import annotations

from datetime import date

import pytest

from core.enums import ImpactLevel
from tests.fakes import FakeCalendarGateway, InMemoryCache
from use_cases.fetch_calendar import FetchEconomicCalendarUseCase


@pytest.mark.asyncio
async def test_filters_by_minimum_impact(economic_events, now) -> None:
    today = now.date()
    gw = FakeCalendarGateway(events_by_day={today: economic_events})
    uc = FetchEconomicCalendarUseCase(calendar=gw, cache=InMemoryCache())

    high_only = await uc.execute(day=today, min_impact=ImpactLevel.HIGH)
    assert [e.name for e in high_only] == ["CPI YoY"]

    medium_or_more = await uc.execute(day=today, min_impact=ImpactLevel.MEDIUM)
    assert {e.name for e in medium_or_more} == {"CPI YoY", "Consumer Confidence"}


@pytest.mark.asyncio
async def test_sorts_by_scheduled_at(economic_events, now) -> None:
    today = now.date()
    reversed_events = list(reversed(economic_events))
    gw = FakeCalendarGateway(events_by_day={today: reversed_events})
    uc = FetchEconomicCalendarUseCase(calendar=gw, cache=InMemoryCache())

    result = await uc.execute(day=today, min_impact=ImpactLevel.LOW)
    timestamps = [e.scheduled_at for e in result]
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio
async def test_uses_today_when_day_not_passed(economic_events, now) -> None:
    gw = FakeCalendarGateway(events_by_day={now.date(): economic_events})
    uc = FetchEconomicCalendarUseCase(calendar=gw, cache=InMemoryCache())

    # No `day` argument — relies on system clock, so we just assert it doesn't blow up.
    result = await uc.execute(min_impact=ImpactLevel.LOW)
    assert isinstance(result, list)
