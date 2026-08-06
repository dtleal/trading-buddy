"""In-process fan-out for live order-flow snapshots.

Mirror of `broadcaster.TickBroadcaster`, but for `OrderFlowSnapshot` messages
which arrive far more frequently than the 5m dashboard tick. The ingest WS
handler (collector → backend) calls `publish(snapshot)` for each updated
symbol; each browser WS connection registers a `subscribe()` that first
replays the latest snapshot per symbol, then streams live updates.

Browser sends are throttled to FLUSH_INTERVAL_SECONDS per symbol (newest wins)
and carry a trimmed payload — see `_for_wire`. The bot and the auto-close read
the untrimmed snapshot straight from the ingest handler, so nothing here can
change what is traded.

Kept on a SEPARATE channel from the dashboard tick on purpose: order flow is
high-frequency and only covers the ORDERFLOW_SYMBOLS subset, so we never want
it inflating the 5m tick payload or coupling its lifecycle to the data loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from core.enums import AssetSymbol
from core.models import OrderFlowSnapshot

logger = logging.getLogger(__name__)

# Keep the per-subscriber queue SHALLOW on purpose: it is what bounds how stale
# the UI can get. Snapshots are absolute and coalesced (see below), so a deep
# buffer would only make a slow tab read older and older data — two flush rounds
# of six symbols is enough slack, and anything past it is dropped, not queued.
SUBSCRIBER_QUEUE_MAXSIZE = 12

# How often the browser channel is flushed. The collector pushes book, tape and
# position messages many times a second PER SYMBOL, and every one of them used
# to send a full snapshot (~70 KB) to every browser. With six symbols that was
# ~3 MB/s per tab: the browser fell behind, its queue filled, the backend closed
# it as slow, and the UI reconnected every ~90s showing frozen P&L. Snapshots
# are absolute (never deltas), so only the newest one per symbol matters —
# publish() records it and this loop sends it at a fixed 4x/s.
FLUSH_INTERVAL_SECONDS = 0.25


def _for_wire(snapshot: OrderFlowSnapshot) -> OrderFlowSnapshot:
    """Strip the per-price cells of every footprint bar except the newest.

    The cells are ~90% of the payload and the UI only draws the ladder of the
    current bar; older bars are drawn from their totals (delta / POC), which
    stay. The bot reads the untouched snapshot, not this copy.
    """
    bars = snapshot.footprint
    if len(bars) <= 1:
        return snapshot
    trimmed = [b.model_copy(update={"cells": []}) for b in bars[:-1]]
    trimmed.append(bars[-1])
    return snapshot.model_copy(update={"footprint": trimmed})


class OrderFlowBroadcaster:
    """Fan-out per-symbol order-flow snapshots to N WebSocket subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[OrderFlowSnapshot]] = set()
        self._latest: dict[AssetSymbol, OrderFlowSnapshot] = {}
        self._pending: dict[AssetSymbol, OrderFlowSnapshot] = {}
        self._flusher: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def latest_all(self) -> list[OrderFlowSnapshot]:
        return list(self._latest.values())

    async def publish(self, snapshot: OrderFlowSnapshot) -> None:
        """Called by the ingest handler. Records the snapshot as the symbol's
        latest; the flush loop sends it to the browsers on the next tick."""
        wire = _for_wire(snapshot)
        self._latest[wire.symbol] = wire
        self._pending[wire.symbol] = wire
        loop = asyncio.get_running_loop()
        if (
            self._flusher is None
            or self._flusher.done()
            or self._flusher.get_loop() is not loop
        ):
            self._flusher = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        """Send the newest snapshot per symbol every FLUSH_INTERVAL_SECONDS."""
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            pending, self._pending = self._pending, {}
            for snapshot in pending.values():
                await self._fanout(snapshot)

    async def _fanout(self, snapshot: OrderFlowSnapshot) -> None:
        async with self._lock:
            for queue in self._subscribers:
                if queue.full():
                    # Client is behind: throw away its oldest snapshot rather
                    # than closing the socket — a newer one is right here.
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:  # pragma: no cover - drained meanwhile
                        pass
                try:
                    queue.put_nowait(snapshot)
                except asyncio.QueueFull:  # pragma: no cover - filled meanwhile
                    logger.warning("Order-flow subscriber queue full — snapshot skipped")

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
