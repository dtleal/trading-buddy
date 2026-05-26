from __future__ import annotations

from datetime import datetime, timezone

import pytest

from day_trading_buddy.core.enums import (
    AssetSymbol,
    BiasLevel,
    LLMOutputKind,
    TermStructure,
    VixRegime,
)
from day_trading_buddy.core.models import (
    BiasComponents,
    BiasReport,
    DashboardTick,
    MacroSnapshot,
    MarketSnapshot,
    PriceQuote,
    VixSnapshot,
)
from day_trading_buddy.use_cases.generate_briefing import GenerateBriefingUseCase
from tests.fakes import FakeLLMGateway, FakeSnapshotRepository, InMemoryCache


def _tick() -> DashboardTick:
    now = datetime.now(timezone.utc)
    market = MarketSnapshot(
        timestamp=now,
        assets={
            AssetSymbol.USTEC: PriceQuote(
                symbol="USTEC", price=20_000.0, timestamp=now, ma200_d=19_000.0
            ),
        },
        vix=VixSnapshot(
            vix=14.0,
            vix9d=13.0,
            vix3m=15.0,
            regime=VixRegime.LOW,
            term_structure=TermStructure.CONTANGO,
        ),
    )
    macro = MacroSnapshot(timestamp=now, indicators={})
    bias = {
        AssetSymbol.USTEC: BiasReport(
            asset=AssetSymbol.USTEC,
            timestamp=now,
            score=65.0,
            level=BiasLevel.BULLISH,
            components=BiasComponents(technical=70.0, macro=60.0, sentiment=60.0),
            rationale=[],
        )
    }
    return DashboardTick(
        timestamp=now,
        market=market,
        macro=macro,
        events_today=[],
        recent_news=[],
        bias=bias,
    )


@pytest.mark.asyncio
async def test_briefing_uses_briefing_kind_and_persists_output() -> None:
    llm = FakeLLMGateway(canned_response="MARKET BRIEFING TEXT")
    cache = InMemoryCache()
    repo = FakeSnapshotRepository()

    uc = GenerateBriefingUseCase(llm=llm, cache=cache, repository=repo, language="pt")
    output = await uc.execute(_tick())

    assert output.kind == LLMOutputKind.BRIEFING
    assert llm.calls[0]["kind"] == LLMOutputKind.BRIEFING
    assert repo.llm_outputs == [output]
    assert await cache.get(f"llm:response:{output.prompt_hash}") == "MARKET BRIEFING TEXT"


@pytest.mark.asyncio
async def test_briefing_in_portuguese_includes_pt_system_prompt() -> None:
    llm = FakeLLMGateway()
    uc = GenerateBriefingUseCase(
        llm=llm, cache=InMemoryCache(), repository=FakeSnapshotRepository(), language="pt"
    )
    await uc.execute(_tick())
    assert "Portuguese" in llm.calls[0]["system_prompt"]


@pytest.mark.asyncio
async def test_briefing_in_english_includes_en_system_prompt() -> None:
    llm = FakeLLMGateway()
    uc = GenerateBriefingUseCase(
        llm=llm, cache=InMemoryCache(), repository=FakeSnapshotRepository(), language="en"
    )
    await uc.execute(_tick())
    assert "Reply in English" in llm.calls[0]["system_prompt"]
