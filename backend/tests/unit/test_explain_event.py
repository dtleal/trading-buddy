from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import ImpactLevel, LLMOutputKind
from core.models import EconomicEvent
from tests.fakes import FakeLLMGateway, FakeSnapshotRepository, InMemoryCache
from use_cases.explain_event import ExplainEventUseCase


def _event() -> EconomicEvent:
    return EconomicEvent(
        name="CPI YoY",
        currency="USD",
        impact=ImpactLevel.HIGH,
        scheduled_at=datetime.now(timezone.utc),
        forecast="2.6%",
        previous="2.7%",
    )


@pytest.mark.asyncio
async def test_pre_event_uses_event_pre_kind() -> None:
    llm = FakeLLMGateway()
    uc = ExplainEventUseCase(
        llm=llm, cache=InMemoryCache(), repository=FakeSnapshotRepository(), language="pt"
    )
    output = await uc.execute(_event(), mode="pre")
    assert output.kind == LLMOutputKind.EVENT_PRE


@pytest.mark.asyncio
async def test_post_event_uses_event_post_kind() -> None:
    llm = FakeLLMGateway()
    uc = ExplainEventUseCase(
        llm=llm, cache=InMemoryCache(), repository=FakeSnapshotRepository(), language="en"
    )
    output = await uc.execute(_event(), mode="post")
    assert output.kind == LLMOutputKind.EVENT_POST
