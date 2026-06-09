"""Aggregate the raw MT5 order-flow stream into flow-trader views.

The collector pushes two kinds of events to the backend ingest socket:

- **book**  — a fresh depth-of-market snapshot (top-N bids/asks).
- **trade** — one executed tick with price, volume and aggressor side.

This use case keeps the rolling per-symbol state needed to render the three
panels a flow trader wants:

- **DOM ladder**  → the latest `OrderBookSnapshot`.
- **Tape**        → the tail of executed trades (`recent_trades`).
- **Footprint**   → executed volume bucketed by (time bar × price), split into
                    bid (sell-aggressor) vs ask (buy-aggressor) volume.

State lives in process memory only. It is single-event-loop, single-thread by
construction (the ingest WS handler calls these methods synchronously between
awaits), so no locking is needed. Restarting the backend resets the flow — it
backfills again from the live stream within seconds.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from datetime import datetime, timezone

from core.enums import AssetSymbol
from core.models import (
    FootprintBar,
    FootprintCell,
    OrderBookSnapshot,
    OrderFlowSnapshot,
    TapeTrade,
)

# Prices are rounded to this many decimals before being used as a footprint
# bucket key. Covers the tick size of every instrument we track (NQ/ES 0.25,
# GC 0.1, CFD index/gold). Avoids float fragmentation across cells.
_PRICE_KEY_DECIMALS = 4


def _bucket_open(at: datetime, interval_seconds: int) -> datetime:
    """Floor `at` to the start of its footprint bar (UTC)."""
    at = at.astimezone(timezone.utc)
    epoch = int(at.timestamp())
    floored = epoch - (epoch % interval_seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


class OrderFlowAggregator:
    """Rolling per-symbol order-flow state. One instance per backend process."""

    def __init__(
        self,
        *,
        symbols: list[AssetSymbol],
        footprint_interval_seconds: int = 60,
        footprint_bars: int = 30,
        tape_maxlen: int = 200,
    ) -> None:
        self._symbols = set(symbols)
        self._interval = footprint_interval_seconds
        self._max_bars = footprint_bars
        self._tape_maxlen = tape_maxlen

        self._books: dict[AssetSymbol, OrderBookSnapshot] = {}
        self._tapes: dict[AssetSymbol, deque[TapeTrade]] = {
            s: deque(maxlen=tape_maxlen) for s in symbols
        }
        # symbol -> bar_open -> price(rounded) -> [bid_volume, ask_volume]
        self._footprints: dict[AssetSymbol, OrderedDict[datetime, dict[float, list[float]]]] = {
            s: OrderedDict() for s in symbols
        }
        self._last_event: dict[AssetSymbol, datetime] = {}

    @property
    def symbols(self) -> set[AssetSymbol]:
        return self._symbols

    def tracks(self, symbol: AssetSymbol) -> bool:
        return symbol in self._symbols

    # --- ingestion --------------------------------------------------------

    def ingest_book(self, book: OrderBookSnapshot) -> OrderFlowSnapshot:
        """Replace the latest DOM for a symbol; return the fresh snapshot."""
        self._books[book.symbol] = book
        self._last_event[book.symbol] = book.asof
        return self.snapshot(book.symbol)

    def ingest_trade(self, trade: TapeTrade) -> OrderFlowSnapshot:
        """Append a trade to the tape + footprint; return the fresh snapshot."""
        symbol = trade.symbol
        self._tapes.setdefault(symbol, deque(maxlen=self._tape_maxlen)).append(trade)

        bars = self._footprints.setdefault(symbol, OrderedDict())
        bucket = _bucket_open(trade.at, self._interval)
        cells = bars.setdefault(bucket, {})
        key = round(trade.price, _PRICE_KEY_DECIMALS)
        cell = cells.setdefault(key, [0.0, 0.0])
        # buy aggressor lifts the ask → ask_volume; sell aggressor hits the bid
        # → bid_volume. `unknown` is split nowhere directional: count it on the
        # ask side only if price ticked up vs nothing — simplest is to drop it
        # into ask_volume=0/bid_volume=0 (still shows on the tape, just not the
        # footprint delta). We keep total volume by adding to whichever side
        # the collector inferred; unknown contributes to neither delta side.
        if trade.side == "buy":
            cell[1] += trade.volume
        elif trade.side == "sell":
            cell[0] += trade.volume

        # Keep only the most recent N buckets.
        while len(bars) > self._max_bars:
            bars.popitem(last=False)

        self._last_event[symbol] = trade.at
        return self.snapshot(symbol)

    # --- read -------------------------------------------------------------

    def snapshot(self, symbol: AssetSymbol) -> OrderFlowSnapshot:
        """Build the broadcast snapshot for one symbol from current state."""
        book = self._books.get(symbol)
        tape = list(self._tapes.get(symbol, ()))
        footprint = self._build_footprint(symbol)
        asof = self._last_event.get(symbol) or datetime.now(timezone.utc)
        return OrderFlowSnapshot(
            symbol=symbol,
            asof=asof,
            book=book,
            recent_trades=tape,
            footprint=footprint,
        )

    def all_snapshots(self) -> list[OrderFlowSnapshot]:
        """Snapshot every tracked symbol that has seen any data."""
        out: list[OrderFlowSnapshot] = []
        for symbol in self._symbols:
            if symbol in self._books or self._tapes.get(symbol):
                out.append(self.snapshot(symbol))
        return out

    def _build_footprint(self, symbol: AssetSymbol) -> list[FootprintBar]:
        bars = self._footprints.get(symbol)
        if not bars:
            return []
        out: list[FootprintBar] = []
        for bar_open, cells in bars.items():
            cell_models = [
                FootprintCell(price=price, bid_volume=bid, ask_volume=ask)
                for price, (bid, ask) in sorted(cells.items(), reverse=True)
            ]
            bid_total = sum(c.bid_volume for c in cell_models)
            ask_total = sum(c.ask_volume for c in cell_models)
            poc = max(
                cell_models,
                key=lambda c: c.bid_volume + c.ask_volume,
                default=None,
            )
            out.append(
                FootprintBar(
                    symbol=symbol,
                    bar_open=bar_open,
                    interval_seconds=self._interval,
                    cells=cell_models,
                    bid_volume=bid_total,
                    ask_volume=ask_total,
                    delta=ask_total - bid_total,
                    poc_price=poc.price if poc else None,
                )
            )
        # OrderedDict preserves insertion (chronological) order already, but be
        # explicit so a late-arriving backfilled bucket can't scramble it.
        out.sort(key=lambda b: b.bar_open)
        return out


__all__ = ["OrderFlowAggregator"]
