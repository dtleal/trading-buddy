"""Fetch the market snapshot (assets + VIX complex) for the current tick."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from core.enums import AssetSymbol, TermStructure, VixRegime
from core.interfaces import CacheStore, PricesGateway
from core.models import MarketSnapshot, PriceQuote, VixSnapshot

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
ASSETS: tuple[AssetSymbol, ...] = (AssetSymbol.USTEC, AssetSymbol.SPX, AssetSymbol.GOLD)


def _classify_vix_regime(value: float) -> VixRegime:
    if value < 15.0:
        return VixRegime.LOW
    if value <= 25.0:
        return VixRegime.MID
    return VixRegime.HIGH


def _classify_term_structure(vix9d: float | None, vix3m: float | None) -> TermStructure:
    if vix9d is None or vix3m is None:
        return TermStructure.FLAT
    if vix9d < vix3m * 0.98:
        return TermStructure.CONTANGO
    if vix9d > vix3m * 1.02:
        return TermStructure.BACKWARDATION
    return TermStructure.FLAT


class FetchMarketSnapshotUseCase:
    """Pulls quotes and 200-period MAs in parallel."""

    def __init__(self, prices: PricesGateway, cache: CacheStore) -> None:
        self._prices = prices
        self._cache = cache

    async def _quote_with_ma(self, symbol: str, *, with_ma: bool) -> PriceQuote:
        cached = await self._cache.get(f"prices:{symbol}")
        if cached:
            try:
                payload = json.loads(cached)
                return PriceQuote.model_validate(payload)
            except Exception:
                logger.debug("Stale or malformed cache for %s, refetching", symbol)

        quote = await self._prices.get_quote(symbol)
        if with_ma:
            ma_d, ma_h4 = await asyncio.gather(
                self._prices.get_ma200(symbol, "1d"),
                self._prices.get_ma200(symbol, "1h"),
            )
            quote = quote.model_copy(update={"ma200_d": ma_d, "ma200_h4": ma_h4})
        await self._cache.set(
            f"prices:{symbol}",
            quote.model_dump_json(),
            ttl_seconds=CACHE_TTL_SECONDS,
        )
        return quote

    async def execute(self) -> MarketSnapshot:
        asset_results, vix, vix9d, vix3m = await asyncio.gather(
            asyncio.gather(*(self._quote_with_ma(a.value, with_ma=True) for a in ASSETS)),
            self._quote_with_ma("VIX", with_ma=False),
            self._quote_with_ma("VIX9D", with_ma=False),
            self._quote_with_ma("VIX3M", with_ma=False),
        )

        assets: dict[AssetSymbol, PriceQuote] = {
            symbol: quote for symbol, quote in zip(ASSETS, asset_results)
        }

        vix_snapshot = VixSnapshot(
            vix=vix.price,
            vix9d=vix9d.price if vix9d.price else None,
            vix3m=vix3m.price if vix3m.price else None,
            regime=_classify_vix_regime(vix.price),
            term_structure=_classify_term_structure(vix9d.price, vix3m.price),
        )

        return MarketSnapshot(
            timestamp=datetime.now(timezone.utc),
            assets=assets,
            vix=vix_snapshot,
        )
