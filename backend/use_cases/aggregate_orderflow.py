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
from statistics import median

from core.enums import AssetSymbol
from core.models import (
    FootprintBar,
    FootprintCell,
    LiveActivity,
    OrderBookSnapshot,
    OrderFlowSnapshot,
    TapeTrade,
)

# Prices are rounded to this many decimals before being used as a footprint
# bucket key. Covers the tick size of every instrument we track (NQ/ES 0.25,
# GC 0.1, CFD index/gold). Avoids float fragmentation across cells.
_PRICE_KEY_DECIMALS = 4

# Hard cap on distinct price cells kept per footprint bar. A quote-tick feed can
# print thousands of slightly-different prices per minute; without a cap the
# per-bar cell dict (and every snapshot built from it) grows unbounded and pegs
# the event loop. Bar-level bid/ask totals are tracked separately, so the delta
# / pressure stay exact even once the visual cell budget is spent.
_MAX_CELLS_PER_BAR = 256


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
        activity_window: int = 5,
    ) -> None:
        self._symbols = set(symbols)
        self._interval = footprint_interval_seconds
        self._max_bars = footprint_bars
        self._tape_maxlen = tape_maxlen
        # How many recent *completed* bars feed the live-activity medians.
        self._activity_window = activity_window

        self._books: dict[AssetSymbol, OrderBookSnapshot] = {}
        self._tapes: dict[AssetSymbol, deque[TapeTrade]] = {
            s: deque(maxlen=tape_maxlen) for s in symbols
        }
        # symbol -> bar_open -> bar state. Each bar is {"cells": {price: [bid, ask]},
        # "bid": float, "ask": float}: cells drive the footprint visual (capped at
        # _MAX_CELLS_PER_BAR), while "bid"/"ask" are exact running totals that drive
        # the delta/pressure regardless of the cell budget.
        self._footprints: dict[AssetSymbol, OrderedDict[datetime, dict]] = {
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
        symbol = self._apply_trade(trade)
        return self.snapshot(symbol)

    def ingest_trades(self, symbol: AssetSymbol, trades: list[TapeTrade]) -> OrderFlowSnapshot:
        """Apply a batch of trades, building the snapshot only once.

        High-rate feeds (e.g. a synthesized quote-tick tape) deliver dozens of
        trades per poll. Rebuilding the full snapshot per trade is O(trades ×
        cells) and pegs the event loop, so the batch path mutates state for each
        trade and snapshots a single time at the end.
        """
        for trade in trades:
            self._apply_trade(trade)
        return self.snapshot(symbol)

    def _apply_trade(self, trade: TapeTrade) -> AssetSymbol:
        """Mutate tape + footprint state for one trade. Returns its symbol."""
        symbol = trade.symbol
        self._tapes.setdefault(symbol, deque(maxlen=self._tape_maxlen)).append(trade)

        bars = self._footprints.setdefault(symbol, OrderedDict())
        bucket = _bucket_open(trade.at, self._interval)
        bar = bars.get(bucket)
        if bar is None:
            bar = bars[bucket] = {"cells": {}, "bid": 0.0, "ask": 0.0}

        # Bar-level totals are exact and drive the delta/pressure — count them
        # first, before the (capped) per-price cell. buy aggressor lifts the ask
        # → ask side; sell aggressor hits the bid → bid side; `unknown` shows on
        # the tape but contributes to neither directional side.
        if trade.side == "buy":
            bar["ask"] += trade.volume
        elif trade.side == "sell":
            bar["bid"] += trade.volume

        cells = bar["cells"]
        key = round(trade.price, _PRICE_KEY_DECIMALS)
        cell = cells.get(key)
        if cell is None and len(cells) < _MAX_CELLS_PER_BAR:
            cell = cells[key] = [0.0, 0.0]
        if cell is not None:
            if trade.side == "buy":
                cell[1] += trade.volume
            elif trade.side == "sell":
                cell[0] += trade.volume

        # Keep only the most recent N buckets.
        while len(bars) > self._max_bars:
            bars.popitem(last=False)

        self._last_event[symbol] = trade.at
        return symbol

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
            live_activity=self._build_live_activity(symbol),
        )

    def all_snapshots(self) -> list[OrderFlowSnapshot]:
        """Snapshot every tracked symbol that has seen any data."""
        out: list[OrderFlowSnapshot] = []
        for symbol in self._symbols:
            if symbol in self._books or self._tapes.get(symbol):
                out.append(self.snapshot(symbol))
        return out

    def _build_live_activity(self, symbol: AssetSymbol) -> LiveActivity | None:
        """Real-time candle-size + volume read from the live footprint.

        Samples the last `_activity_window` *completed* bars (the most recent
        bucket is still in progress, so its range/volume is partial — exclude it
        when there's more than one). Range is the bar's traded high−low (top
        minus bottom price cell); volume is the exact bar total. No baseline
        needed, so this fills the instant flow arrives; the collector's
        `SessionLiquidity` ratio layers "vs normal" on top when available.
        """
        bars = self._footprints.get(symbol)
        if not bars:
            return None
        items = list(bars.values())
        completed = items[:-1] if len(items) > 1 else items
        sample = completed[-self._activity_window :]
        if not sample:
            return None
        ranges: list[float] = []
        volumes: list[float] = []
        for bar in sample:
            cells = bar["cells"]
            if cells:
                prices = cells.keys()
                ranges.append(max(prices) - min(prices))
            else:
                ranges.append(0.0)
            volumes.append(bar["bid"] + bar["ask"])
        return LiveActivity(
            range_per_bar=float(median(ranges)),
            volume_per_bar=float(median(volumes)),
            interval_seconds=self._interval,
            sampled_bars=len(sample),
        )

    def _build_footprint(self, symbol: AssetSymbol) -> list[FootprintBar]:
        bars = self._footprints.get(symbol)
        if not bars:
            return []
        out: list[FootprintBar] = []
        for bar_open, bar in bars.items():
            cell_models = [
                FootprintCell(price=price, bid_volume=bid, ask_volume=ask)
                for price, (bid, ask) in sorted(bar["cells"].items(), reverse=True)
            ]
            # Totals come from the exact bar-level counters, not the (capped)
            # cells, so delta/pressure stay correct even when cells are clipped.
            bid_total = bar["bid"]
            ask_total = bar["ask"]
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
