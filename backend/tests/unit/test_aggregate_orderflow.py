"""Unit tests for the order-flow aggregator (DOM / tape / footprint state)."""

from __future__ import annotations

from datetime import datetime, timezone

from core.enums import AssetSymbol
from core.models import OrderBookLevel, OrderBookSnapshot, TapeTrade
from use_cases.aggregate_orderflow import OrderFlowAggregator


def _agg(**kw) -> OrderFlowAggregator:
    defaults = dict(
        symbols=[AssetSymbol.USTEC, AssetSymbol.SPX, AssetSymbol.GOLD],
        footprint_interval_seconds=60,
        footprint_bars=3,
        tape_maxlen=5,
    )
    defaults.update(kw)
    return OrderFlowAggregator(**defaults)


def _trade(price: float, volume: float, side: str, second: int) -> TapeTrade:
    return TapeTrade(
        symbol=AssetSymbol.USTEC,
        at=datetime(2026, 6, 9, 14, 0, second, tzinfo=timezone.utc),
        price=price,
        volume=volume,
        side=side,  # type: ignore[arg-type]
    )


def test_tracks_only_configured_symbols() -> None:
    agg = _agg(symbols=[AssetSymbol.GOLD])
    assert agg.tracks(AssetSymbol.GOLD)
    assert not agg.tracks(AssetSymbol.USTEC)
    assert not agg.tracks(AssetSymbol.BITCOIN)


def test_ingest_book_replaces_latest() -> None:
    agg = _agg()
    book = OrderBookSnapshot(
        symbol=AssetSymbol.USTEC,
        asof=datetime(2026, 6, 9, 14, 0, 0, tzinfo=timezone.utc),
        bids=[OrderBookLevel(price=100.0, volume=5.0)],
        asks=[OrderBookLevel(price=100.5, volume=3.0)],
    )
    snap = agg.ingest_book(book)
    assert snap.book is not None
    assert snap.book.bids[0].volume == 5.0
    # a second book wins
    book2 = book.model_copy(update={"bids": [OrderBookLevel(price=100.0, volume=9.0)]})
    snap2 = agg.ingest_book(book2)
    assert snap2.book.bids[0].volume == 9.0


def test_footprint_splits_aggressor_into_bid_ask() -> None:
    agg = _agg()
    agg.ingest_trade(_trade(100.0, 2.0, "buy", 1))
    agg.ingest_trade(_trade(100.0, 3.0, "sell", 2))
    snap = agg.ingest_trade(_trade(100.0, 1.0, "buy", 3))

    assert len(snap.footprint) == 1
    bar = snap.footprint[0]
    cell = next(c for c in bar.cells if c.price == 100.0)
    assert cell.ask_volume == 3.0  # 2 + 1 buy
    assert cell.bid_volume == 3.0  # 3 sell
    assert bar.ask_volume == 3.0
    assert bar.bid_volume == 3.0
    assert bar.delta == 0.0
    assert bar.poc_price == 100.0


def test_unknown_side_excluded_from_delta_but_on_tape() -> None:
    agg = _agg()
    snap = agg.ingest_trade(_trade(100.0, 4.0, "unknown", 1))
    bar = snap.footprint[0]
    cell = bar.cells[0]
    assert cell.bid_volume == 0.0
    assert cell.ask_volume == 0.0
    assert bar.delta == 0.0
    # still visible on the tape
    assert len(snap.recent_trades) == 1
    assert snap.recent_trades[0].volume == 4.0


def test_separate_time_buckets_make_separate_bars() -> None:
    agg = _agg()
    agg.ingest_trade(_trade(100.0, 1.0, "buy", 10))  # bar 14:00:00
    snap = agg.ingest_trade(
        TapeTrade(
            symbol=AssetSymbol.USTEC,
            at=datetime(2026, 6, 9, 14, 1, 5, tzinfo=timezone.utc),  # bar 14:01:00
            price=100.0,
            volume=2.0,
            side="buy",
        )
    )
    assert len(snap.footprint) == 2
    assert snap.footprint[0].bar_open < snap.footprint[1].bar_open


def test_footprint_bars_are_capped() -> None:
    agg = _agg(footprint_bars=2)
    for minute in range(4):
        agg.ingest_trade(
            TapeTrade(
                symbol=AssetSymbol.USTEC,
                at=datetime(2026, 6, 9, 14, minute, 0, tzinfo=timezone.utc),
                price=100.0,
                volume=1.0,
                side="buy",
            )
        )
    snap = agg.snapshot(AssetSymbol.USTEC)
    assert len(snap.footprint) == 2  # only the last 2 buckets retained
    assert snap.footprint[-1].bar_open.minute == 3


def test_tape_is_bounded() -> None:
    agg = _agg(tape_maxlen=3)
    for i in range(5):
        agg.ingest_trade(_trade(100.0 + i, 1.0, "buy", i))
    snap = agg.snapshot(AssetSymbol.USTEC)
    assert len(snap.recent_trades) == 3
    assert snap.recent_trades[-1].price == 104.0  # newest kept


def test_all_snapshots_only_includes_symbols_with_data() -> None:
    agg = _agg()
    agg.ingest_trade(_trade(100.0, 1.0, "buy", 1))
    snaps = agg.all_snapshots()
    assert {s.symbol for s in snaps} == {AssetSymbol.USTEC}
