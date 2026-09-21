"""The seam between the file and the live RTD feed.

The file holds the session up to the moment Profit opened the Times & Trades
window; the collector holds the last 500 prints from then on. Joining them
wrong is the difference between "the day so far" and either half a day or a
double-counted one, so each side of the join is pinned down here.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from adapters.profit_tape import TYPE_BUY_AGGRESSION, TapeFile, Trade
from api.routes import players as route
from use_cases.aggregate_players import PlayersAccumulator

# `_feed_live` stamps the session with the real São Paulo date, so the fixture
# has to live on the same day or every seed would be read as yesterday's file.
TODAY = datetime.now(route.B3_TZ).date()
OPEN = datetime.combine(TODAY, time(9, 0))
XP, UBS = 3, 8


def trade(minute: int, qty: int = 1) -> Trade:
    return Trade(
        at=OPEN + timedelta(minutes=minute),
        seq=0,
        price=140000.0,
        qty=qty,
        financial=140000.0 * qty * 0.20,
        buyer=UBS,
        seller=XP,
        kind=TYPE_BUY_AGGRESSION,
    )


def wire(minute: int) -> dict[str, object]:
    stamp = (OPEN + timedelta(minutes=minute)).strftime("%H:%M:%S.%f")[:-3]
    return {
        "at": stamp,
        "buyer": "UBS",
        "price": 140000.0,
        "qty": 1,
        "seller": "XP",
        "aggressor": "Comprador",
    }


def batch(*minutes: int) -> dict[str, object]:
    return {"type": "b3_trades", "asset": "WINV26", "trades": [wire(m) for m in minutes]}


def reader_with(minutes: list[int], day: date | None = None, pending: int = 0) -> route._Reader:
    accumulator = PlayersAccumulator()
    accumulator.feed([trade(m) for m in minutes])
    return route._Reader(
        file=TapeFile(path=Path("fake.trd"), symbol="WINFUT", day=day or TODAY),
        offset=0,
        accumulator=accumulator,
        pending_bytes=pending,
    )


@pytest.fixture(autouse=True)
def clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route, "_live", {})
    monkeypatch.setattr(route, "_readers", {})
    monkeypatch.setattr(route, "_codes", {"xp": XP, "ubs": UBS})
    monkeypatch.setattr(route, "_agents", {XP: "XP", UBS: "UBS"})
    monkeypatch.setattr(route, "_loading", False)


def test_live_carries_on_from_what_the_file_already_counted() -> None:
    route._readers["WIN"] = reader_with([0, 1, 2])  # 09:00, 09:01, 09:02
    # The window still shows 09:02 plus two prints the file never saw.
    route._feed_live(batch(2, 3, 4))
    live = route._live["WIN"]
    assert live.seeded is True
    assert live.cut == OPEN + timedelta(minutes=2)
    # Three from the file, two new; the repeated 09:02 is not counted twice.
    assert live.accumulator.trades == 5
    assert live.duplicates == 1
    assert live.accumulator.first_trade == OPEN


def test_a_file_from_another_day_is_not_carried_into_today() -> None:
    route._readers["WIN"] = reader_with([0, 1, 2], day=TODAY - timedelta(days=3))
    route._feed_live(batch(3, 4))
    live = route._live["WIN"]
    assert live.seeded is True
    assert live.cut is None
    assert live.accumulator.trades == 2  # today starts at the live feed
    assert live.accumulator.first_trade == OPEN + timedelta(minutes=3)


def test_prints_wait_while_the_file_is_still_being_read() -> None:
    route._readers["WIN"] = reader_with([0], pending=10_000_000)
    route._feed_live(batch(3, 4))
    live = route._live["WIN"]
    assert live.seeded is False
    assert len(live.pending) == 2
    assert live.accumulator.trades == 0  # nothing counted yet

    # Reader finishes: the held prints go in on top of the file's session.
    route._readers["WIN"] = reader_with([0, 1], pending=0)
    route._feed_live(batch(5))
    live = route._live["WIN"]
    assert live.seeded is True
    assert live.accumulator.trades == 5  # 2 from file + 3 held/new
    assert live.pending == []


def test_waiting_gives_up_when_the_file_never_arrives() -> None:
    route._feed_live(batch(3))  # no reader at all
    live = route._live["WIN"]
    assert live.seeded is False  # still hoping

    live.deadline = 0.0  # pretend the wait ran out
    route._feed_live(batch(4))
    live = route._live["WIN"]
    assert live.seeded is True
    assert live.cut is None
    assert live.accumulator.trades == 2  # the held print is not thrown away
