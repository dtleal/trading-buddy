"""CME tab: lot-size groups, aggressions, recording, and the routing from the
B3 ingest."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

import api.routes.cme as cme
import api.routes.players as players
from use_cases.aggregate_cme import MARKETS, CmeAccumulator, CmePrint, market_of


def _p(sec: int, qty: float, buy: bool, price: float = 4300.0) -> CmePrint:
    return CmePrint(datetime(2026, 9, 23, 10, 0) + timedelta(seconds=sec), price, qty, buy)


def test_symbols_map_to_their_market_and_micros_count_a_tenth() -> None:
    assert market_of("GCZ26") == (MARKETS["GC"], 1.0)
    assert market_of("MGCZ26") == (MARKETS["GC"], 0.1)
    assert market_of("MESZ26") == (MARKETS["ES"], 0.1)
    assert market_of("@NQ") == (MARKETS["NQ"], 1.0)
    assert market_of("WINV26") is None


def test_groups_come_from_the_print_size() -> None:
    book = CmeAccumulator(MARKETS["GC"])
    book.feed([_p(1, 12, True), _p(2, 4, False), _p(3, 1, True)])
    snap = book.snapshot("2026-09-23", datetime(2026, 9, 23, 10, 0, 5))
    saldo = {p.key: p.saldo for p in snap.players}
    assert saldo == {"baleia": 12, "banco": -4, "sardinha": 1}
    whale = next(p for p in snap.players if p.key == "baleia")
    assert whale.saldo_rs == 12 * 4300 * 100  # USD, GC is $100 a point
    assert not snap.stale


def test_a_big_one_sided_burst_is_an_aggression_and_sardinha_is_not() -> None:
    book = CmeAccumulator(MARKETS["GC"])
    book.feed([_p(i, 15, True) for i in range(10)])  # 150 contracts of baleia buying
    book.feed([_p(20 + i // 2, 2, False) for i in range(100)])  # 200 of sardinha selling
    rows = book.snapshot("2026-09-23", datetime(2026, 9, 23, 10, 5)).aggressions
    assert [(r["agressor"], r["lado"], r["qty"]) for r in rows] == [("BALEIA", "COMPRA", 150)]


def _message(rows: list[tuple[str, int, str]], asset: str = "GCZ26") -> dict:
    return {
        "type": "b3_trades",
        "asset": asset,
        "trades": [
            {"at": at, "buyer": "", "price": 4300.5, "qty": qty, "seller": "", "aggressor": agr}
            for at, qty, agr in rows
        ],
    }


@pytest.fixture
def fresh(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    for name in ("_books", "_days", "_cuts", "_dropped"):
        monkeypatch.setattr(cme, name, {})
    monkeypatch.setattr(cme, "_tape_path", lambda asset, day: tmp_path / f"{asset}_{day}.jsonl")


def test_the_b3_ingest_hands_cme_windows_to_the_cme_tab(fresh) -> None:
    players._feed_live(_message([("10:00:01.000", 12, "Comprador"), ("10:00:02.000", 1, "Vendedor")]))
    body = asyncio.run(cme.cme_players())
    (gc,) = body.assets
    assert gc.asset == "GC" and gc.symbol == "GCZ26" and gc.trades == 2


def test_unreadable_rows_are_dropped_not_guessed(fresh) -> None:
    cme.feed(_message([("10:00:01.000", 3, "Leilao"), ("xx", 3, "Comprador")]))
    assert cme._dropped["GC"] == 2


def test_a_restart_rebuilds_the_day_without_counting_the_overlap_twice(fresh) -> None:
    first = [("10:00:01.000", 12, "Comprador"), ("10:00:02.000", 4, "Vendedor")]
    cme.feed(_message(first))
    cme._books.clear()  # the backend restarts
    cme.feed(_message(first + [("10:00:03.000", 1, "Comprador")]))  # the window repeats itself
    assert cme._books["GC"].trades == 3
