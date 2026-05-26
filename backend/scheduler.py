"""5-minute tick loop.

The CLI's `run` command instantiates `TickScheduler` with the dashboard tick
use case and a callback that updates the Rich Live() display.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from core.models import DashboardTick
from use_cases.run_dashboard_tick import RunDashboardTickUseCase

logger = logging.getLogger(__name__)

TickCallback = Callable[[DashboardTick], None]


class TickScheduler:
    """Minimal async loop. An `asyncio.wait_for` loop is enough at this
    cadence; we can swap in APScheduler if we need cron-style or multi-job
    scheduling later."""

    def __init__(
        self,
        *,
        interval_seconds: int,
        tick_use_case: RunDashboardTickUseCase,
        on_tick: TickCallback,
    ) -> None:
        self._interval = interval_seconds
        self._tick = tick_use_case
        self._on_tick = on_tick
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return  # stop signal received
            except asyncio.TimeoutError:
                pass

            try:
                tick = await self._tick.execute()
                self._on_tick(tick)
            except Exception:
                logger.exception("Tick failed; will retry next interval")
