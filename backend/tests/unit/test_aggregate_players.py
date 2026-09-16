"""Unit tests for the Baleia / Banco / Sardinha read and the .trd parser."""

from __future__ import annotations

import struct
from datetime import date, datetime, timedelta
from pathlib import Path

from adapters.profit_tape import (
    RECORD,
    TapeFile,
    archive_tape,
    TYPE_BUY_AGGRESSION,
    TYPE_RLP,
    TYPE_SELL_AGGRESSION,
    Trade,
    find_tape_files,
    load_agents,
    read_trades,
)
from use_cases.aggregate_players import PlayersAccumulator, aggregate_players

MORGAN = 40  # baleia
BRADESCO = 72  # banco (mesa)
XP = 3  # sardinha
ITAU_CORRETORA = 114  # sardinha: é a corretora do banco, não a mesa
SESSION = datetime(2026, 9, 14, 10, 0)
DELPHI_EPOCH = datetime(1899, 12, 30)


# WDO's multiplier, so the reais in the tests are the reais B3 would print.
MULTIPLIER = 10


def _trade(minute: int, price: float, qty: int, buyer: int, seller: int, kind: int) -> Trade:
    return Trade(
        at=SESSION + timedelta(minutes=minute),
        seq=minute * 10,
        price=price,
        qty=qty,
        financial=price * qty * MULTIPLIER,
        buyer=buyer,
        seller=seller,
        kind=kind,
    )


def _snapshot(trades: list[Trade], now: datetime | None = None):
    return aggregate_players(
        trades,
        {MORGAN: "Morgan", BRADESCO: "Bradesco", XP: "XP"},
        "WDO",
        "WDOV26",
        "2026-09-14",
        now or SESSION + timedelta(minutes=30),
    )


def _by_key(snapshot) -> dict:
    return {player.key: player for player in snapshot.players}


def test_aggression_nets_by_group() -> None:
    # Morgan (baleia) buys 100 from Itaú (banco), aggressing.
    snapshot = _snapshot([_trade(0, 5000, 100, MORGAN, BRADESCO, TYPE_BUY_AGGRESSION)])
    players = _by_key(snapshot)
    assert players["baleia"].saldo == 100
    assert players["banco"].saldo == -100
    # 100 contratos a 5000 pontos, multiplicador 10 = R$ 5.000.000
    assert players["baleia"].saldo_rs == 5_000_000
    assert players["banco"].saldo_rs == -5_000_000
    # The buyer took liquidity, so all of the whale's volume was aggressive.
    assert players["baleia"].agressao_pct == 100.0
    assert players["banco"].agressao_pct == 0.0


def test_trade_inside_one_group_cancels_out() -> None:
    snapshot = _snapshot([_trade(0, 5000, 50, MORGAN, MORGAN, TYPE_SELL_AGGRESSION)])
    players = _by_key(snapshot)
    assert players["baleia"].saldo == 0
    # Gross still counts both legs: the group did trade.
    assert players["baleia"].volume == 100


def test_rlp_is_its_own_read_and_stays_out_of_the_partition() -> None:
    trades = [
        _trade(0, 5000, 10, XP, MORGAN, TYPE_BUY_AGGRESSION),  # seeds the price
        _trade(1, 5001, 30, XP, XP, TYPE_RLP),  # uptick -> retail bought
        _trade(2, 5000, 20, XP, XP, TYPE_RLP),  # downtick -> retail sold
    ]
    players = _by_key(_snapshot(trades))
    assert players["rlp"].saldo == 10  # +30 - 20
    assert players["rlp"].fonte == "rlp"
    # Internalizado não toca o book, então não entra no saldo da sardinha nem
    # desequilibra a partição.
    assert players["sardinha"].saldo == 10  # só a agressão que abriu o teste
    assert players["sardinha"].volume == 10


def test_the_three_groups_always_add_up_to_zero() -> None:
    """Cada agressão tem duas pontas e cada corretora cai num grupo só, então o
    resto tem que ser zero. Se não for, sobrou corretora fora do mapa."""
    trades = [
        _trade(0, 5000, 10, XP, MORGAN, TYPE_BUY_AGGRESSION),
        _trade(1, 5001, 40, BRADESCO, XP, TYPE_SELL_AGGRESSION),
        _trade(2, 5002, 7, MORGAN, 99999, TYPE_BUY_AGGRESSION),  # corretora desconhecida
    ]
    snapshot = _snapshot(trades)
    assert snapshot.residual_rs == 0
    players = _by_key(snapshot)
    assert players["baleia"].saldo_rs + players["banco"].saldo_rs + players["sardinha"].saldo_rs == 0


def test_a_banks_brokerage_is_sardinha_not_banco() -> None:
    """Itaú CV (114) roteia cliente de varejo — 26% do fluxo dele vem por RLP.
    Contar isso como BANCO foi o que fez a linha do banco ir pra +R$ 776 mi
    quando a referência tinha ela perto de zero."""
    players = _by_key(
        _snapshot([_trade(0, 5000, 100, ITAU_CORRETORA, MORGAN, TYPE_BUY_AGGRESSION)])
    )
    assert players["sardinha"].saldo == 100
    assert players["banco"].saldo == 0


def test_side_reads_the_recent_window_not_the_session() -> None:
    # Bought early, sold late: nearly flat on the day, selling right now.
    trades = [_trade(0, 5000, 500, MORGAN, BRADESCO, TYPE_BUY_AGGRESSION)]
    trades += [
        _trade(minute, 5000, 200, BRADESCO, MORGAN, TYPE_SELL_AGGRESSION)
        for minute in (40, 45, 47)
    ]
    players = _by_key(_snapshot(trades, now=SESSION + timedelta(minutes=48)))
    assert players["baleia"].saldo == -100
    # The 10:00 buy is outside the 15-minute window, so only the selling counts.
    assert players["baleia"].saldo_recente == -600
    assert players["baleia"].lado == "SELL"


def test_recent_window_is_minutes_not_buckets() -> None:
    # One lonely print in the morning, then nothing for hours: the morning
    # print must not be reported as "últimos 15 min".
    trades = [
        _trade(0, 5000, 500, MORGAN, BRADESCO, TYPE_BUY_AGGRESSION),
        _trade(300, 5000, 10, MORGAN, BRADESCO, TYPE_BUY_AGGRESSION),
    ]
    players = _by_key(_snapshot(trades, now=SESSION + timedelta(minutes=301)))
    assert players["baleia"].saldo == 510
    assert players["baleia"].saldo_recente == 10


def test_lag_and_stale_track_the_last_print() -> None:
    trades = [_trade(0, 5000, 10, MORGAN, BRADESCO, TYPE_BUY_AGGRESSION)]
    fresh = _snapshot(trades, now=SESSION + timedelta(seconds=30))
    assert fresh.lag_seconds == 30
    assert fresh.stale is False
    # Profit writes the tape in bursts, so a couple of minutes behind is normal.
    assert _snapshot(trades, now=SESSION + timedelta(minutes=3)).stale is False
    old = _snapshot(trades, now=SESSION + timedelta(minutes=10))
    assert old.lag_seconds == 600
    assert old.stale is True


def test_accumulator_fed_in_chunks_matches_one_shot() -> None:
    trades = [
        _trade(minute, 5000 + minute, 10 + minute, MORGAN, XP, TYPE_BUY_AGGRESSION)
        for minute in range(40)
    ]
    chunked = PlayersAccumulator()
    for start in range(0, len(trades), 7):
        chunked.feed(trades[start : start + 7])
    now = SESSION + timedelta(minutes=45)
    left = chunked.snapshot({}, "WDO", "WDOV26", "2026-09-14", now)
    right = _snapshot(trades, now=now)
    assert [(p.key, p.saldo, p.saldo_recente) for p in left.players] == [
        (p.key, p.saldo, p.saldo_recente) for p in right.players
    ]


def _write_tape(path: Path, trades: list[Trade]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for trade in trades:
            handle.write(
                RECORD.pack(
                    (trade.at - DELPHI_EPOCH).total_seconds() / 86400,
                    trade.seq,
                    trade.price,
                    trade.qty,
                    0,
                    trade.financial,
                    trade.buyer,
                    trade.seller,
                    trade.kind,
                )
            )


def _append_tape(path: Path, trades: list[Trade]) -> None:
    scratch = path.with_suffix(".tmp")
    _write_tape(scratch, trades)
    with path.open("ab") as handle:
        handle.write(scratch.read_bytes())
    scratch.unlink()


def test_read_trades_resumes_from_offset(tmp_path: Path) -> None:
    path = tmp_path / "WDOV26_F_0_0_1_1_1_0_20260914.trd"
    _write_tape(path, [_trade(0, 5000, 1, XP, MORGAN, TYPE_BUY_AGGRESSION)])
    trades, offset, pending = read_trades(path)
    assert len(trades) == 1
    assert offset == RECORD.size
    assert pending == 0

    _append_tape(path, [_trade(1, 5001, 2, MORGAN, XP, TYPE_SELL_AGGRESSION)])
    trades, offset, pending = read_trades(path, offset)
    assert len(trades) == 1  # only the appended print comes back
    assert trades[0].qty == 2
    assert offset == RECORD.size * 2
    assert pending == 0


def test_read_trades_honours_the_slice_budget(tmp_path: Path) -> None:
    path = tmp_path / "WDOV26_F_0_0_1_1_1_0_20260914.trd"
    _write_tape(
        path,
        [_trade(i, 5000 + i, 1, XP, MORGAN, TYPE_BUY_AGGRESSION) for i in range(10)],
    )
    trades, offset, pending = read_trades(path, 0, max_bytes=RECORD.size * 4)
    assert len(trades) == 4
    assert offset == RECORD.size * 4
    assert pending == RECORD.size * 6  # the loop knows it is still catching up


def test_read_trades_ignores_a_half_written_record(tmp_path: Path) -> None:
    path = tmp_path / "WDOV26_F_0_0_1_1_1_0_20260914.trd"
    _write_tape(path, [_trade(0, 5000, 1, XP, MORGAN, TYPE_BUY_AGGRESSION)])
    with path.open("ab") as handle:
        handle.write(b"\x00" * 20)  # Profit caught mid-write
    trades, offset, _ = read_trades(path)
    assert len(trades) == 1
    assert offset == RECORD.size


def test_find_tape_files_picks_the_newest_session(tmp_path: Path) -> None:
    folder = tmp_path / "database" / "assets" / "WDOV26_F_0"
    for day in ("20260910", "20260914"):
        _write_tape(
            folder / f"WDOV26_F_0_0_1_1_1_0_{day}.trd",
            [_trade(0, 5000, 1, XP, MORGAN, TYPE_BUY_AGGRESSION)],
        )
    found = find_tape_files(tmp_path, ("WDO",))
    assert found["WDO"].symbol == "WDOV26"
    assert found["WDO"].day.isoformat() == "2026-09-14"


def test_archive_keeps_a_copy_and_refreshes_it_while_it_grows(tmp_path: Path) -> None:
    source = tmp_path / "WDOV26_F_0_0_1_1_1_0_20260914.trd"
    _write_tape(source, [_trade(0, 5000, 1, XP, MORGAN, TYPE_BUY_AGGRESSION)])
    tape = TapeFile(path=source, symbol="WDOV26", day=date(2026, 9, 14))
    archive = tmp_path / "arquivo"

    archive_tape(tape, archive)
    copy = archive / "WDOV26_2026-09-14.trd"
    assert copy.stat().st_size == RECORD.size

    _append_tape(source, [_trade(1, 5001, 2, MORGAN, XP, TYPE_SELL_AGGRESSION)])
    archive_tape(tape, archive)
    assert copy.stat().st_size == RECORD.size * 2
    # Nada de .part sobrando depois de uma cópia que deu certo.
    assert list(archive.glob("*.part")) == []


def test_archive_never_shrinks_what_is_already_saved(tmp_path: Path) -> None:
    """Se o Profit reabrir a sessão e gravar um arquivo menor, a cópia inteira
    que já temos vale mais do que a nova."""
    source = tmp_path / "WDOV26_F_0_0_1_1_1_0_20260914.trd"
    _write_tape(source, [_trade(i, 5000, 1, XP, MORGAN, TYPE_BUY_AGGRESSION) for i in range(5)])
    tape = TapeFile(path=source, symbol="WDOV26", day=date(2026, 9, 14))
    archive = tmp_path / "arquivo"
    archive_tape(tape, archive)

    _write_tape(source, [_trade(0, 5000, 1, XP, MORGAN, TYPE_BUY_AGGRESSION)])
    archive_tape(tape, archive)
    assert (archive / "WDOV26_2026-09-14.trd").stat().st_size == RECORD.size * 5


def test_load_agents_skips_the_header_comment(tmp_path: Path) -> None:
    (tmp_path / "newagents.dat").write_text(
        "//11/08/2026 14:59:46.600\r\n"
        "3:XP Investimentos CCTVM S/A:XP:30/12/1899:1:66,70\r\n"
        "lixo\r\n",
        encoding="latin-1",
    )
    assert load_agents(tmp_path) == {3: "XP"}


def test_missing_broker_table_is_not_fatal(tmp_path: Path) -> None:
    assert load_agents(tmp_path) == {}
