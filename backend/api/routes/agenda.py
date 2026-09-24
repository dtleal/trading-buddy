"""REST endpoint: today's scheduled news for WIN, WDO and GOLD, plus headlines.

The frontend reads `eventos` to sound the alert 30, 15 and 5 minutes before
each one. Cached for a few minutes: the calendar does not change by the minute,
and the three sites should not be hit on every poll.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic

import anyio
from fastapi import APIRouter
from pydantic import BaseModel

from adapters.agenda import BRT, fetch_events, fetch_headlines

router = APIRouter(prefix="/api/agenda", tags=["agenda"])

_TTL_SECONDS = 180.0


class AgendaEventModel(BaseModel):
    at: datetime
    country: str
    title: str
    importance: int
    source: str
    forecast: str | None
    previous: str | None
    actual: str | None


class HeadlineModel(BaseModel):
    at: datetime
    title: str
    url: str
    source: str


class AgendaResponse(BaseModel):
    eventos: list[AgendaEventModel]
    manchetes: list[HeadlineModel]


_cache: tuple[float, AgendaResponse] | None = None


@router.get("", response_model=AgendaResponse)
async def agenda() -> AgendaResponse:
    global _cache
    if _cache is not None and monotonic() - _cache[0] < _TTL_SECONDS:
        return _cache[1]
    today = datetime.now(timezone.utc).astimezone(BRT).date()
    events = await fetch_events(today)
    headlines = await anyio.to_thread.run_sync(fetch_headlines)
    payload = AgendaResponse(
        eventos=[AgendaEventModel.model_validate(e, from_attributes=True) for e in events],
        manchetes=[HeadlineModel.model_validate(h, from_attributes=True) for h in headlines],
    )
    _cache = (monotonic(), payload)
    return payload
