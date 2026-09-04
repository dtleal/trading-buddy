"""Unit tests for the collector's deal → closed-trade grouping.

`_group_deals_into_trades` is the piece that decides what a "trade" is for the
Performance tab: it folds MT5 deals that share a position id into one round
trip, sums the money actually banked and reads the origin (manual vs bot) from
the entry deal. It's a pure function, so we test it here with stub deals — the
MetaTrader5 package itself only exists on Windows.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_COLLECTOR_DIR = Path(__file__).resolve().parents[3] / "collector"
sys.path.insert(0, str(_COLLECTOR_DIR))

from mt5_orderflow_collector import (  # noqa: E402
    _BOT_MAGIC,
    _DEAL_ENTRY_IN,
    _DEAL_TYPE_BUY,
    _DEAL_TYPE_SELL,
    _collect_cash_flows,
    _group_deals_into_trades,
)

MAP = {"UsaTecSep26": "USTEC"}
# 2026-03-02 14:00:00 UTC as a server-epoch second (the collector's clock offset
# is zero in tests, so server epoch == UTC epoch here).
T0 = 1772460000.0


@dataclass
class Deal:
    """The fields the grouping helper reads off an MT5 deal."""

    position_id: int
    symbol: str
    type: int
    entry: int
    volume: float
    price: float
    time: float
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    magic: int = 0
    comment: str = ""
    ticket: int = 0


def entry_deal(pid: int, **kw) -> Deal:
    base = dict(
        position_id=pid,
        symbol="UsaTecSep26",
        type=_DEAL_TYPE_BUY,
        entry=_DEAL_ENTRY_IN,
        volume=0.01,
        price=100.0,
        time=T0,
    )
    return Deal(**{**base, **kw})


def exit_deal(pid: int, **kw) -> Deal:
    base = dict(
        position_id=pid,
        symbol="UsaTecSep26",
        type=_DEAL_TYPE_SELL,
        entry=1,  # DEAL_ENTRY_OUT
        volume=0.01,
        price=110.0,
        time=T0 + 60,
        profit=10.0,
    )
    return Deal(**{**base, **kw})


def test_one_position_becomes_one_trade_with_the_net_banked() -> None:
    trades = _group_deals_into_trades(
        [entry_deal(1, commission=-0.2), exit_deal(1, commission=-0.2, swap=-0.1)], MAP
    )
    assert len(trades) == 1
    trade = trades[0]
    assert trade["id"] == 1
    assert trade["symbol"] == "USTEC"  # mapped to the backend name
    assert trade["broker_symbol"] == "UsaTecSep26"
    assert trade["side"] == "buy"
    assert trade["source"] == "manual"
    assert trade["lots"] == 0.01
    assert trade["open_price"] == 100.0
    assert trade["close_price"] == 110.0
    assert trade["net"] == 9.5  # 10 profit - 0.4 commission - 0.1 swap
    assert trade["open_ts"].startswith("2026-03-02T14:00")
    assert trade["close_ts"].startswith("2026-03-02T14:01")


def test_partial_fills_are_volume_weighted() -> None:
    trades = _group_deals_into_trades(
        [
            entry_deal(7, volume=0.01, price=100.0),
            entry_deal(7, volume=0.03, price=104.0, time=T0 + 10),
            exit_deal(7, volume=0.02, price=110.0, profit=6.0, time=T0 + 30),
            exit_deal(7, volume=0.02, price=112.0, profit=8.0, time=T0 + 40),
        ],
        MAP,
    )
    assert len(trades) == 1
    trade = trades[0]
    assert trade["lots"] == 0.04
    assert trade["open_price"] == 103.0  # (0.01*100 + 0.03*104) / 0.04
    assert trade["close_price"] == 111.0
    assert trade["net"] == 14.0
    assert trade["close_ts"].endswith("14:00:40+00:00")  # last exit wins


def test_the_bot_magic_marks_the_trade_as_the_bots() -> None:
    trades = _group_deals_into_trades(
        [entry_deal(2, magic=_BOT_MAGIC, comment="trading-buddy sc"), exit_deal(2)], MAP
    )
    assert trades[0]["source"] == "bot"


def test_old_bot_trades_are_recognised_by_their_comment() -> None:
    """Trades the bot opened before the magic number existed still carry the
    (broker-truncated) comment."""
    trades = _group_deals_into_trades(
        [entry_deal(3, magic=0, comment="trading-buddy sc"), exit_deal(3)], MAP
    )
    assert trades[0]["source"] == "bot"


def test_our_autoclose_comment_on_the_exit_does_not_relabel_a_manual_trade() -> None:
    trades = _group_deals_into_trades(
        [entry_deal(4), exit_deal(4, comment="trading-buddy autoclose", magic=0)], MAP
    )
    assert trades[0]["source"] == "manual"


def test_open_positions_and_balance_operations_are_skipped() -> None:
    trades = _group_deals_into_trades(
        [
            entry_deal(5),  # no exit yet — still open
            Deal(  # a balance/credit operation (deal type 2)
                position_id=0, symbol="", type=2, entry=0, volume=0.0, price=0.0, time=T0
            ),
        ],
        MAP,
    )
    assert trades == []


def test_unmapped_broker_symbol_keeps_its_own_spelling() -> None:
    trades = _group_deals_into_trades(
        [entry_deal(6, symbol="XAUUSD.old"), exit_deal(6, symbol="XAUUSD.old")], MAP
    )
    assert trades[0]["symbol"] == "XAUUSD.old"


def test_a_sell_trade_is_labelled_by_its_entry_deal() -> None:
    trades = _group_deals_into_trades(
        [
            entry_deal(8, type=_DEAL_TYPE_SELL, price=110.0),
            exit_deal(8, type=_DEAL_TYPE_BUY, price=100.0, profit=10.0),
        ],
        MAP,
    )
    assert trades[0]["side"] == "sell"
    assert trades[0]["net"] == 10.0


def test_trades_come_back_oldest_close_first() -> None:
    trades = _group_deals_into_trades(
        [
            entry_deal(10, time=T0),
            exit_deal(10, time=T0 + 300),
            entry_deal(11, time=T0 + 10),
            exit_deal(11, time=T0 + 60),
        ],
        MAP,
    )
    assert [t["id"] for t in trades] == [11, 10]


def balance_deal(ticket: int, amount: float, comment: str = "", dtype: int = 2) -> Deal:
    """A balance operation (deposit / withdrawal / transfer): MT5 books the
    money on `profit` with no symbol and no position."""
    return Deal(
        position_id=0,
        symbol="",
        type=dtype,
        entry=0,
        volume=0.0,
        price=0.0,
        time=T0,
        profit=amount,
        comment=comment,
        ticket=ticket,
    )


def test_cash_flows_split_deposits_from_withdrawals() -> None:
    flows = _collect_cash_flows(
        [
            balance_deal(10, 1000.0, "12641814 Deposit Treviso"),
            balance_deal(11, -250.0, "11609797 TRF to 80005047"),
            entry_deal(1),  # a trade — never a cash flow
            exit_deal(1),
        ]
    )
    assert [(f["id"], f["amount"], f["kind"]) for f in flows] == [
        (10, 1000.0, "deposit"),
        (11, -250.0, "withdrawal"),
    ]
    assert flows[0]["comment"] == "12641814 Deposit Treviso"
    assert flows[0]["ts"].startswith("2026-03-02T14:00")


def test_zero_value_bookkeeping_markers_are_dropped() -> None:
    """The broker writes a 0.00 "Archive" balance deal at year end."""
    assert _collect_cash_flows([balance_deal(12, 0.0, "Archive 2024-12-31")]) == []


def test_credit_and_commission_deals_are_kept_as_other() -> None:
    flows = _collect_cash_flows([balance_deal(13, -1.5, "commission", dtype=7)])
    assert [(f["amount"], f["kind"]) for f in flows] == [(-1.5, "other")]
