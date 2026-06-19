"""Unit tests for the day-outlook ntfy push (once-per-day, regime-aware dedup)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import DayRegime
from core.models import DayOutlook
from tests.fakes import InMemoryCache
from use_cases.push_day_outlook_alerts import PushDayOutlookAlertsUseCase


class FakeNotifier:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.sent: list[dict] = []

    async def push(self, *, title, message, priority, tags) -> bool:
        self.sent.append({"title": title, "message": message, "priority": priority, "tags": tags})
        return True


def _outlook(regime: DayRegime, *, day: int = 19, score: float = 10.0) -> DayOutlook:
    return DayOutlook(
        asof=datetime(2026, 6, day, 13, 0, tzinfo=timezone.utc),
        score=score,
        regime=regime,
        headline="x",
        rationale=["a", "b"],
    )


@pytest.mark.asyncio
async def test_pushes_once_per_day_for_same_regime() -> None:
    notifier = FakeNotifier()
    uc = PushDayOutlookAlertsUseCase(notifier=notifier, cache=InMemoryCache())

    assert await uc.execute(_outlook(DayRegime.THIN)) is True
    assert await uc.execute(_outlook(DayRegime.THIN)) is False  # deduped same day+regime
    assert len(notifier.sent) == 1


@pytest.mark.asyncio
async def test_normal_regime_is_silent() -> None:
    notifier = FakeNotifier()
    uc = PushDayOutlookAlertsUseCase(notifier=notifier, cache=InMemoryCache())
    assert await uc.execute(_outlook(DayRegime.NORMAL)) is False
    assert notifier.sent == []


@pytest.mark.asyncio
async def test_regime_change_repushes_same_day() -> None:
    notifier = FakeNotifier()
    uc = PushDayOutlookAlertsUseCase(notifier=notifier, cache=InMemoryCache())
    assert await uc.execute(_outlook(DayRegime.THIN)) is True
    # Same day, but the day flipped to EXPANSION → user should be told.
    assert await uc.execute(_outlook(DayRegime.EXPANSION)) is True
    assert len(notifier.sent) == 2


@pytest.mark.asyncio
async def test_disabled_notifier_never_pushes() -> None:
    notifier = FakeNotifier(enabled=False)
    uc = PushDayOutlookAlertsUseCase(notifier=notifier, cache=InMemoryCache())
    assert await uc.execute(_outlook(DayRegime.THIN)) is False
    assert notifier.sent == []
