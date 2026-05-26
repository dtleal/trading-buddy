"""CME FedWatch HTML scraper.

The public FedWatch widget exposes a structured JSON payload via
`https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html` but
that endpoint changes occasionally. Until we settle on a stable source, this
adapter returns `None` and a follow-up issue tracks fixing it.

The structure is here so the use case wiring stays correct; replace the body
of `get_fedwatch` with the actual scrape when ready.
"""

from __future__ import annotations

import logging

import httpx

from core.models import FedWatchProbability, MacroIndicator

logger = logging.getLogger(__name__)


class FedWatchMacroGateway:
    """Implements `core.interfaces.MacroGateway` partially (only FedWatch)."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=15.0, follow_redirects=True)

    async def get_indicator(self, series_id: str) -> MacroIndicator | None:  # noqa: ARG002
        return None

    async def get_fedwatch(self) -> FedWatchProbability | None:
        # Real implementation deferred — see module docstring.
        return None

    async def close(self) -> None:
        await self._client.aclose()
