"""REST endpoint: VIX intraday history (5m bars)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from adapters.prices_yfinance import YFinancePricesGateway
from core.models import IntradayBar


class VixHistoryResponse(BaseModel):
    """Bars + latest spot + last update timestamp."""

    symbol: str = Field(examples=["VIX"])
    bars: list[IntradayBar]
    count: int


def _prices_gateway() -> YFinancePricesGateway:
    # FastAPI dependency. Fresh gateway per request — yfinance is sync,
    # backed by httpx through the lib internals; safe and cheap.
    return YFinancePricesGateway()


router = APIRouter(prefix="/api/vix", tags=["vix"])


@router.get("/history", response_model=VixHistoryResponse)
async def vix_history(
    interval: Annotated[str, Query(description="Bar interval (5m default)")] = "5m",
    lookback_days: Annotated[
        int, Query(ge=1, le=60, description="Days of history (yfinance cap: 60d)")
    ] = 2,
    prices: YFinancePricesGateway = Depends(_prices_gateway),
) -> VixHistoryResponse:
    bars = await prices.get_intraday_bars("VIX", interval, lookback_days)
    if not bars:
        raise HTTPException(
            status_code=503, detail="No VIX bars returned (market closed or rate-limited)"
        )
    return VixHistoryResponse(symbol="VIX", bars=bars, count=len(bars))
