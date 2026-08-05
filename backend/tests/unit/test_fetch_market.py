from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import TRACKED_ASSETS, AssetSymbol, TermStructure, VixRegime
from core.models import PriceQuote
from tests.fakes import FakePricesGateway, InMemoryCache
from use_cases.fetch_market import FetchMarketSnapshotUseCase


@pytest.mark.asyncio
async def test_fetch_market_returns_all_assets_and_vix() -> None:
    now = datetime.now(timezone.utc)
    prices = FakePricesGateway(
        quotes={
            "USTEC": PriceQuote(symbol="USTEC", price=20_000.0, timestamp=now),
            "SPX": PriceQuote(symbol="SPX", price=5_900.0, timestamp=now),
            "GOLD": PriceQuote(symbol="GOLD", price=2_600.0, timestamp=now),
            "US30": PriceQuote(symbol="US30", price=44_000.0, timestamp=now),
            "USOIL": PriceQuote(symbol="USOIL", price=68.0, timestamp=now),
            "US2000": PriceQuote(symbol="US2000", price=2_400.0, timestamp=now),
            "VIX": PriceQuote(symbol="VIX", price=14.0, timestamp=now),
            "VIX9D": PriceQuote(symbol="VIX9D", price=13.0, timestamp=now),
            "VIX3M": PriceQuote(symbol="VIX3M", price=15.0, timestamp=now),
        },
        ma200_map={
            ("USTEC", "1d"): 19_000.0,
            ("USTEC", "1h"): 19_500.0,
            ("SPX", "1d"): 5_600.0,
            ("SPX", "1h"): 5_700.0,
            ("GOLD", "1d"): 2_500.0,
            ("GOLD", "1h"): 2_550.0,
            ("US30", "1d"): 42_000.0,
            ("US30", "1h"): 43_000.0,
            ("USOIL", "1d"): 70.0,
            ("USOIL", "1h"): 69.0,
            ("US2000", "1d"): 2_300.0,
            ("US2000", "1h"): 2_350.0,
        },
    )

    uc = FetchMarketSnapshotUseCase(prices=prices, cache=InMemoryCache())
    snapshot = await uc.execute()

    assert set(snapshot.assets) == set(TRACKED_ASSETS)
    assert snapshot.vix.regime == VixRegime.LOW
    assert snapshot.vix.term_structure == TermStructure.CONTANGO
    assert snapshot.assets[AssetSymbol.USTEC].ma200_d == 19_000.0


@pytest.mark.asyncio
async def test_high_vix_triggers_high_regime() -> None:
    now = datetime.now(timezone.utc)
    prices = FakePricesGateway(
        quotes={
            "USTEC": PriceQuote(symbol="USTEC", price=20_000.0, timestamp=now),
            "SPX": PriceQuote(symbol="SPX", price=5_900.0, timestamp=now),
            "GOLD": PriceQuote(symbol="GOLD", price=2_600.0, timestamp=now),
            "VIX": PriceQuote(symbol="VIX", price=32.0, timestamp=now),
            "VIX9D": PriceQuote(symbol="VIX9D", price=35.0, timestamp=now),
            "VIX3M": PriceQuote(symbol="VIX3M", price=30.0, timestamp=now),
        }
    )
    snapshot = await FetchMarketSnapshotUseCase(prices=prices, cache=InMemoryCache()).execute()
    assert snapshot.vix.regime == VixRegime.HIGH
    assert snapshot.vix.term_structure == TermStructure.BACKWARDATION
