"""In-process fan-out for live order-flow snapshots.

Mirror of `broadcaster.TickBroadcaster`, but for `OrderFlowSnapshot` messages
which arrive far more frequently than the 5m dashboard tick. The ingest WS
handler (collector → backend) calls `publish(snapshot)` for each updated
symbol; each browser WS connection registers a `subscribe()` that first
replays the latest snapshot per symbol, then streams live updates.

Kept on a SEPARATE channel from the dashboard tick on purpose: order flow is
high-frequency and only covers USTEC / SPX / GOLD, so we never want it
inflating the 5m tick payload or coupling its lifecycle to the data loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from core.enums import AssetSymbol
from core.models import OrderFlowSnapshot

logger = logging.getLogger(__name__)

# Order flow is bursty; give subscribers more headroom than the tick channel
# before we drop a slow client.
SUBSCRIBER_QUEUE_MAXSIZE = 64


class OrderFlowBroadcaster:
    """Fan-out per-symbol order-flow snapshots to N WebSocket subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[OrderFlowSnapshot]] = set()
        self._latest: dict[AssetSymbol, OrderFlowSnapshot] = {}
        self._lock = asyncio.Lock()

    def latest_all(self) -> list[OrderFlowSnapshot]:
        return list(self._latest.values())

    async def publish(self, snapshot: OrderFlowSnapshot) -> None:
        """Called by the ingest handler. Non-blocking — slow clients dropped."""
        self._latest[snapshot.symbol] = snapshot
        async with self._lock:
            stale: list[asyncio.Queue[OrderFlowSnapshot]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(snapshot)
                except asyncio.QueueFull:
                    stale.append(queue)
            for queue in stale:
                self._subscribers.discard(queue)
                logger.warning("Dropping slow order-flow subscriber (queue full)")

    async def subscribe(self) -> AsyncIterator[OrderFlowSnapshot]:
        """Async generator for the browser WS handler. Yields until cancelled."""
        queue: asyncio.Queue[OrderFlowSnapshot] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            # Replay the latest snapshot for each symbol so a fresh client sees
            # the current book/tape/footprint immediately instead of a blank
            # panel until the next trade prints.
            for snapshot in self._latest.values():
                queue.put_nowait(snapshot)
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                self._subscribers.discard(queue)


# Process-wide singleton, shared by the ingest route and the browser route.
orderflow_broadcaster = OrderFlowBroadcaster()
