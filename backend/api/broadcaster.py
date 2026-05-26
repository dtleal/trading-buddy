"""In-process pub/sub bridge between the tick loop and connected WebSocket clients.

The tick loop (`cli/main.py:_run_loop`) calls `publish(tick)` once per fresh
data fetch. Each WS connection registers a `subscribe()` which yields ticks
until the client disconnects. Slow clients are dropped — we never block the
tick loop on a stuck consumer.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from core.models import DashboardTick

logger = logging.getLogger(__name__)

# Per-client queue size. If a client falls behind, we drop them rather than
# accumulating memory on a wedged consumer.
SUBSCRIBER_QUEUE_MAXSIZE = 8


class TickBroadcaster:
    """Fan-out a single tick stream to N WebSocket subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[DashboardTick]] = set()
        self._latest: DashboardTick | None = None
        self._lock = asyncio.Lock()

    @property
    def latest(self) -> DashboardTick | None:
        return self._latest

    async def publish(self, tick: DashboardTick) -> None:
        """Called by the tick loop. Non-blocking — slow subscribers are dropped."""
        self._latest = tick
        async with self._lock:
            stale: list[asyncio.Queue[DashboardTick]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(tick)
                except asyncio.QueueFull:
                    stale.append(queue)
            for queue in stale:
                self._subscribers.discard(queue)
                logger.warning("Dropping slow WS subscriber (queue full)")

    async def subscribe(self) -> AsyncIterator[DashboardTick]:
        """Async generator used by the WS handler. Yields ticks until cancelled."""
        queue: asyncio.Queue[DashboardTick] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            # Replay the latest tick immediately so a fresh client doesn't sit
            # blank for up to a full TICK_INTERVAL_SECONDS.
            if self._latest is not None:
                queue.put_nowait(self._latest)
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers.discard(queue)


# Process-wide singleton. The tick loop and the API share this instance.
broadcaster = TickBroadcaster()
