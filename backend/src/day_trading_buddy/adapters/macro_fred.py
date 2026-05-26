"""FRED (St. Louis Fed) macro adapter.

`fredapi` is sync — calls are dispatched to a thread pool.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from day_trading_buddy.core.models import FedWatchProbability, MacroIndicator

logger = logging.getLogger(__name__)

# Series we care about by default.
DEFAULT_SERIES: dict[str, str] = {
    "DFF": "Fed funds rate (effective)",
    "DGS10": "10-year Treasury yield",
    "DTWEXBGS": "Broad dollar index (DXY proxy)",
    "CPIAUCSL": "CPI all items",
    "UNRATE": "Unemployment rate",
}


class FREDMacroGateway:
    """Implements `core.interfaces.MacroGateway` for FRED data only.

    FedWatch lives in a different adapter; this one returns None for it.
    """

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key
        self._client: object | None = None

    def _client_sync(self) -> object:
        if self._client is None:
            if not self._api_key:
                raise RuntimeError("FRED_API_KEY is not configured")
            from fredapi import Fred  # local import to avoid hard dep at import time

            self._client = Fred(api_key=self._api_key)
        return self._client

    def _fetch_indicator_sync(self, series_id: str) -> MacroIndicator | None:
        client = self._client_sync()
        series = client.get_series(series_id)  # type: ignore[attr-defined]
        if series is None or series.empty:
            return None
        last_value = float(series.iloc[-1])
        observed_at = series.index[-1].to_pydatetime().replace(tzinfo=timezone.utc)
        delta_1d: float | None = None
        delta_1w: float | None = None
        if len(series) >= 2:
            delta_1d = last_value - float(series.iloc[-2])
        if len(series) >= 6:
            delta_1w = last_value - float(series.iloc[-6])
        return MacroIndicator(
            series_id=series_id,
            value=last_value,
            observed_at=observed_at,
            delta_1d=delta_1d,
            delta_1w=delta_1w,
        )

    async def get_indicator(self, series_id: str) -> MacroIndicator | None:
        if not self._api_key:
            return None
        try:
            return await asyncio.to_thread(self._fetch_indicator_sync, series_id)
        except Exception as exc:  # pragma: no cover - network/auth failure
            logger.warning("FRED fetch failed for %s: %s", series_id, exc)
            return None

    async def get_fedwatch(self) -> FedWatchProbability | None:
        # FedWatch is not in FRED — see `macro_fedwatch.py`.
        return None
