"""The live RTD feed only earns trust if the two conversions are right: the
sliding window into "what is new", and a window row into a tape `Trade`.
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

from adapters.profit_rtd import (
    aggressor_kind,
    multiplier_for,
    name_to_code,
    parse_time,
    parse_trade,
)
from adapters.profit_tape import TYPE_BUY_AGGRESSION, TYPE_RLP, TYPE_SELL_AGGRESSION

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "collector"))
from profit_rtd_collector import new_rows  # noqa: E402

DAY = date(2026, 9, 21)
AGENTS = {
    3: "XP",
    85: "BTG",
    1026: "BTG",
    114: "Itau",
    2028: "Itau Unibanco",
    4090: "Santander",
    622: "Santander",
}
CODES = name_to_code(AGENTS)


def row(clock: str, buyer: str, price: float, qty: int, seller: str, agr: str) -> dict:
    return {
        "at": clock,
        "buyer": buyer,
        "price": price,
        "qty": qty,
        "seller": seller,
        "aggressor": agr,
    }


# --- sliding window ---------------------------------------------------------


def window(start: int, size: int = 30) -> list[tuple]:
    """A fake window, newest first: line 0 is the highest number."""
    return [(n,) for n in range(start, start - size, -1)]


def test_nothing_new_when_the_window_did_not_move() -> None:
    assert new_rows(window(100), window(100), match=5) == ([], False)


def test_first_read_has_no_previous_to_compare_against() -> None:
    assert new_rows(window(100), None, match=5) == ([], False)


def test_only_the_prints_above_the_old_top_come_back() -> None:
    rows, overflowed = new_rows(window(103), window(100), match=5)
    assert rows == [(103,), (102,), (101,)]
    assert overflowed is False


def test_repeated_prints_do_not_fool_the_match() -> None:
    # Every row identical except the top: a 1-row match would land on line 1
    # and report nothing new.
    previous = [(9,)] + [(1,)] * 29
    current = [(10,), (9,)] + [(1,)] * 28
    rows, overflowed = new_rows(current, previous, match=5)
    assert rows == [(10,)]
    assert overflowed is False


def test_window_rolling_over_is_reported_not_hidden() -> None:
    rows, overflowed = new_rows(window(500), window(100), match=5)
    assert overflowed is True
    assert len(rows) == 30  # the whole window, so the loss is bounded


# --- one row to a Trade -----------------------------------------------------


def test_broker_name_resolves_to_the_code_that_actually_trades() -> None:
    # BTG is 85 (sardinha) and 1026 (banco); Santander is 622 (banco) and 4090
    # (the brokerage). Only 85 and 4090 traded WIN on 18/09/2026.
    assert CODES["btg"] == 85
    assert CODES["santander"] == 4090
    # A name that is not ambiguous still resolves normally.
    assert CODES["xp"] == 3
    assert CODES["itau"] == 114
    assert CODES["itau unibanco"] == 2028


def test_clock_parses_with_and_without_milliseconds() -> None:
    assert parse_time("10:05:03.250", DAY) == datetime(2026, 9, 21, 10, 5, 3, 250000)
    assert parse_time("10:05:03", DAY) == datetime(2026, 9, 21, 10, 5, 3)
    assert parse_time("-", DAY) is None


def test_aggressor_column_maps_to_the_trade_type() -> None:
    assert aggressor_kind("Comprador") == TYPE_BUY_AGGRESSION
    assert aggressor_kind("Vendedor") == TYPE_SELL_AGGRESSION
    assert aggressor_kind("C") == TYPE_BUY_AGGRESSION
    assert aggressor_kind("V") == TYPE_SELL_AGGRESSION
    # RLP is in the column too, so the retail line survives on the live feed.
    assert aggressor_kind("RLP") == TYPE_RLP
    assert aggressor_kind("Leilao") is None


def test_a_good_row_becomes_a_trade_with_the_b3_multiplier() -> None:
    trade = parse_trade(
        row("10:05:03.250", "XP", 140000.0, 3, "BTG", "Comprador"), DAY, 0.20, CODES
    )
    assert trade is not None
    assert trade.buyer == 3
    assert trade.seller == 85
    assert trade.qty == 3
    assert trade.kind == TYPE_BUY_AGGRESSION
    # WIN is R$ 0,20 per point: 140.000 × 3 × 0,20.
    assert trade.financial == 84000.0


def test_an_rlp_print_keeps_its_own_type() -> None:
    # Both sides carry the same broker on an RLP print, by rule.
    trade = parse_trade(row("10:05:03.250", "BTG", 140000.0, 1, "BTG", "RLP"), DAY, 0.20, CODES)
    assert trade is not None
    assert trade.kind == TYPE_RLP
    assert trade.buyer == trade.seller == 85


def test_rows_that_cannot_be_trusted_are_dropped() -> None:
    bad = [
        row("-", "XP", 140000.0, 3, "BTG", "Comprador"),  # empty line
        row("10:05:03", "NaoExiste", 140000.0, 3, "BTG", "C"),  # broker off the map
        row("10:05:03", "XP", 140000.0, 3, "NaoExiste", "C"),  # the other side
        row("10:05:03", "XP", 140000.0, 3, "BTG", "Leilao"),  # no side to pick
        row("10:05:03", "XP", 0.0, 3, "BTG", "C"),  # no price
        row("10:05:03", "XP", 140000.0, 0, "BTG", "C"),  # no quantity
    ]
    assert [parse_trade(r, DAY, 0.20, CODES) for r in bad] == [None] * len(bad)


def test_multiplier_follows_the_contract_prefix() -> None:
    assert multiplier_for("WINV26") == 0.20
    assert multiplier_for("WDOV26") == 10.0
    assert multiplier_for("PETR4") is None


def test_a_read_that_just_fits_is_not_called_an_overflow() -> None:
    # 30 lines, match 5: 25 new prints still leave the old top inside the
    # window, at the very last offset that can be checked.
    rows, overflowed = new_rows(window(125), window(100), match=5)
    assert overflowed is False
    assert len(rows) == 25


class FakeServer:
    """Enough of the RTD server to build a window without Profit."""

    def ConnectData(self, topic_id: int, topic: list, alive: bool) -> str:  # noqa: N802
        return "-"


def test_switching_the_window_to_another_contract_publishes_nothing() -> None:
    from profit_rtd_collector import TapeWindow

    win = TapeWindow(FakeServer(), "T&T0", "WINV26", lines=30, first_id=1)
    win.previous = window(100)
    win.asset_changed("WDOV26")
    assert win.asset == "WDOV26"
    # Baseline dropped: the next pass can only set a new one, never publish the
    # other contract's prints as if they were this one's.
    assert win.previous is None
    assert win.take_new_rows() == []


def test_a_row_with_a_column_out_of_place_is_dropped_not_raised() -> None:
    from profit_rtd_collector import _row_to_trade

    # Seen once in 8.503 replayed rows: a broker name where the quantity goes.
    bent = ("10:05:03.250", "XP", 187000.0, "BTG", "BTG", "Comprador")
    assert _row_to_trade(bent) is None
    # An empty line of a window that has not filled yet.
    assert _row_to_trade(("-", "-", 0.0, 0, "-", "-")) is None
    # And a good row still goes through.
    good = ("10:05:03.250", "XP", 187000.0, 2, "BTG", "Comprador")
    assert _row_to_trade(good) == {
        "at": "10:05:03.250",
        "buyer": "XP",
        "price": 187000.0,
        "qty": 2,
        "seller": "BTG",
        "aggressor": "Comprador",
    }


def test_a_cme_row_without_brokers_still_goes_through() -> None:
    from profit_rtd_collector import _row_to_trade

    row = _row_to_trade(("10:05:03.250", None, 4312.4, 3, None, "Vendedor"))
    assert row is not None and row["buyer"] == "" and row["seller"] == "" and row["qty"] == 3
