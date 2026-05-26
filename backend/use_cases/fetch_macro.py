"""Fetch the macro indicator basket and FedWatch probabilities."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from core.interfaces import CacheStore, MacroGateway
from core.models import MacroIndicator, MacroSnapshot

logger = logging.getLogger(__name__)

DEFAULT_SERIES: tuple[str, ...] = ("DFF", "DGS10", "DTWEXBGS", "CPIAUCSL", "UNRATE")
CACHE_TTL_SECONDS = 3600


class FetchMacroIndicatorsUseCase:
    """Pulls the basket from a primary macro gateway plus FedWatch."""

    def __init__(
        self,
        primary: MacroGateway,
        fedwatch: MacroGateway,
        cache: CacheStore,
        *,
        series: tuple[str, ...] = DEFAULT_SERIES,
    ) -> None:
        self._primary = primary
        self._fedwatch = fedwatch
        self._cache = cache
        self._series = series

    async def execute(self) -> MacroSnapshot:
        indicator_results, fedwatch = await asyncio.gather(
            asyncio.gather(*(self._primary.get_indicator(s) for s in self._series)),
            self._fedwatch.get_fedwatch(),
        )
        indicators: dict[str, MacroIndicator] = {}
        for series_id, ind in zip(self._series, indicator_results):
            if ind is not None:
                indicators[series_id] = ind

        return MacroSnapshot(
            timestamp=datetime.now(timezone.utc),
            indicators=indicators,
            fedwatch=fedwatch,
        )
