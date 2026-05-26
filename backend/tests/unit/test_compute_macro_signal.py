from __future__ import annotations

from datetime import datetime, timezone

import pytest

from day_trading_buddy.core.enums import AssetSymbol
from day_trading_buddy.core.models import FedWatchProbability, MacroIndicator, MacroSnapshot
from day_trading_buddy.use_cases.compute_macro_signal import ComputeMacroSignalUseCase


@pytest.mark.asyncio
async def test_falling_yields_help_both_stocks_and_gold(macro_snapshot: MacroSnapshot) -> None:
    result = await ComputeMacroSignalUseCase().execute(macro_snapshot)
    assert result[AssetSymbol.USTEC].score > 50.0
    assert result[AssetSymbol.GOLD].score > 50.0


@pytest.mark.asyncio
async def test_strong_dollar_punishes_gold(now: datetime) -> None:
    snapshot = MacroSnapshot(
        timestamp=now,
        indicators={
            "DTWEXBGS": MacroIndicator(
                series_id="DTWEXBGS",
                value=120.0,
                observed_at=now,
                delta_1d=0.5,
                delta_1w=1.5,
            )
        },
    )
    result = await ComputeMacroSignalUseCase().execute(snapshot)
    assert result[AssetSymbol.GOLD].score < 50.0


@pytest.mark.asyncio
async def test_fedwatch_cuts_help_stocks() -> None:
    now = datetime.now(timezone.utc)
    snapshot = MacroSnapshot(
        timestamp=now,
        indicators={},
        fedwatch=FedWatchProbability(
            meeting_date=now, cut_50=0.4, cut_25=0.4, hold=0.15, hike_25=0.05
        ),
    )
    result = await ComputeMacroSignalUseCase().execute(snapshot)
    assert result[AssetSymbol.SPX].score > 50.0
