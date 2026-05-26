"""Shared pytest fixtures."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterator

import pytest

from core.enums import (
    AssetSymbol,
    ImpactLevel,
    TermStructure,
    VixRegime,
)
from core.models import (
    EconomicEvent,
    MacroIndicator,
    MacroSnapshot,
    MarketSnapshot,
    NewsItem,
    PriceQuote,
    VixSnapshot,
)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 5, 26, 13, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def market_snapshot(now: datetime) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=now,
        assets={
            AssetSymbol.USTEC: PriceQuote(
                symbol="USTEC",
                price=20_400.0,
                timestamp=now,
                ma200_d=19_200.0,
                change_pct=0.42,
            ),
            AssetSymbol.SPX: PriceQuote(
                symbol="SPX",
                price=5_900.0,
                timestamp=now,
                ma200_d=5_650.0,
                change_pct=0.18,
            ),
            AssetSymbol.GOLD: PriceQuote(
                symbol="GOLD",
                price=2_600.0,
                timestamp=now,
                ma200_d=2_540.0,
                change_pct=-0.31,
            ),
        },
        vix=VixSnapshot(
            vix=14.8,
            vix9d=13.5,
            vix3m=15.2,
            regime=VixRegime.LOW,
            term_structure=TermStructure.CONTANGO,
        ),
    )


@pytest.fixture
def macro_snapshot(now: datetime) -> MacroSnapshot:
    return MacroSnapshot(
        timestamp=now,
        indicators={
            "DGS10": MacroIndicator(
                series_id="DGS10",
                value=4.20,
                observed_at=now,
                delta_1d=-0.03,
                delta_1w=-0.10,
            ),
            "DTWEXBGS": MacroIndicator(
                series_id="DTWEXBGS",
                value=119.5,
                observed_at=now,
                delta_1d=0.05,
                delta_1w=-0.30,
            ),
        },
        fedwatch=None,
    )


@pytest.fixture
def news_items(now: datetime) -> list[NewsItem]:
    return [
        NewsItem(
            headline="Nvidia beats earnings, guidance strong",
            source="MarketWatch",
            url="https://example.com/news/1",
            published_at=now,
        ),
        NewsItem(
            headline="Powell warns rates may stay higher for longer",
            source="Reuters",
            url="https://example.com/news/2",
            published_at=now,
        ),
        NewsItem(
            headline="Oil prices fall on inventory build",
            source="CNBC",
            url="https://example.com/news/3",
            published_at=now,
        ),
    ]


@pytest.fixture
def economic_events(now: datetime) -> list[EconomicEvent]:
    return [
        EconomicEvent(
            name="CPI YoY",
            currency="USD",
            impact=ImpactLevel.HIGH,
            scheduled_at=now,
            forecast="2.6%",
            previous="2.7%",
        ),
        EconomicEvent(
            name="Consumer Confidence",
            currency="USD",
            impact=ImpactLevel.MEDIUM,
            scheduled_at=now,
            forecast="103.0",
            previous="101.8",
        ),
    ]
