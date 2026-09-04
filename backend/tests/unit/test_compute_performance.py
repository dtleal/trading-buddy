"""Unit tests for the Performance metrics (hit rate, drawdown, buckets...).

Pins down the numbers the Performance tab shows, on a hand-built trade list
where every metric can be checked by hand.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.models import CashFlow, ClosedTrade
from use_cases.compute_performance import compute_performance, compute_stats

BASE = datetime(2026, 3, 2, 14, 0, tzinfo=timezone.utc)  # a Monday


def trade(
    tid: int,
    net: float,
    *,
    minutes: int = 0,
    symbol: str = "USTEC",
    source: str = "manual",
    side: str = "buy",
    lots: float = 0.01,
    duration_s: int = 60,
) -> ClosedTrade:
    close = BASE + timedelta(minutes=minutes)
    return ClosedTrade(
        id=tid,
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        lots=lots,
        open_ts=close - timedelta(seconds=duration_s),
        close_ts=close,
        open_price=100.0,
        close_price=101.0,
        net=net,
    )


def flow(fid: int, amount: float, *, minutes: int = 0, kind: str = "deposit") -> CashFlow:
    return CashFlow(
        id=fid,
        ts=BASE + timedelta(minutes=minutes),
        amount=amount,
        kind=kind,  # type: ignore[arg-type]
        comment="Deposit",
    )


def test_stats_on_empty_list_are_all_zero() -> None:
    stats = compute_stats([])
    assert stats.trades == 0
    assert stats.win_rate == 0.0
    assert stats.profit_factor is None
    assert stats.payoff is None


def test_hit_rate_and_win_loss_split() -> None:
    stats = compute_stats(
        [
            trade(1, 10.0),
            trade(2, -5.0, minutes=1),
            trade(3, 20.0, minutes=2),
            trade(4, 0.0, minutes=3),
        ]
    )
    assert stats.trades == 4
    assert (stats.wins, stats.losses, stats.breakeven) == (2, 1, 1)
    assert stats.win_rate == 50.0  # 2 of 4
    assert stats.loss_rate == 25.0
    assert stats.net == 25.0
    assert stats.gross_profit == 30.0
    assert stats.gross_loss == 5.0
    assert stats.profit_factor == 6.0
    assert stats.avg_win == 15.0
    assert stats.avg_loss == 5.0
    assert stats.payoff == 3.0  # risk-return in money
    assert stats.expectancy == 6.25
    assert (stats.best, stats.worst) == (20.0, -5.0)


def test_consecutive_streaks_follow_close_order() -> None:
    stats = compute_stats(
        [
            trade(1, 5.0),
            trade(2, 5.0, minutes=1),
            trade(3, -2.0, minutes=2),
            trade(4, -2.0, minutes=3),
            trade(5, -2.0, minutes=4),
            trade(6, 5.0, minutes=5),
        ]
    )
    assert stats.max_consecutive_wins == 2
    assert stats.max_consecutive_losses == 3


def test_equity_curve_starts_at_the_balance_before_the_window() -> None:
    trades = [trade(1, 100.0), trade(2, -40.0, minutes=1), trade(3, 60.0, minutes=2)]
    # Account is at 1120 now, so it started the window at 1120 - 120 = 1000.
    report = compute_performance(trades, account_balance=1120.0)
    assert report.start_balance == 1000.0
    assert [p.balance for p in report.equity_curve] == [1100.0, 1060.0, 1120.0]
    assert report.end_balance == 1120.0
    assert report.return_pct == 12.0  # +120 on 1000


def test_drawdown_is_measured_on_the_account_balance() -> None:
    trades = [trade(1, 100.0), trade(2, -50.0, minutes=1), trade(3, 10.0, minutes=2)]
    report = compute_performance(trades, account_balance=1060.0)
    # Peak 1100 after the first trade, trough 1050 after the second.
    assert report.max_drawdown == 50.0
    assert report.max_drawdown_pct == 4.55  # 50 / 1100
    assert report.current_drawdown == 40.0  # 1100 - 1060
    assert report.recovery_factor == 1.2  # net 60 / dd 50


def test_filters_by_window_symbol_and_source() -> None:
    trades = [
        trade(1, 10.0, symbol="USTEC", source="manual"),
        trade(2, -5.0, minutes=10, symbol="GOLD", source="bot"),
        trade(3, 7.0, minutes=20, symbol="USTEC", source="bot"),
    ]
    only_bot = compute_performance(trades, account_balance=1012.0, source="bot")
    assert only_bot.summary.trades == 2
    assert only_bot.summary.net == 2.0

    only_ustec = compute_performance(trades, account_balance=1012.0, symbols=["ustec"])
    assert only_ustec.summary.trades == 2
    assert only_ustec.summary.net == 17.0

    windowed = compute_performance(
        trades, account_balance=1012.0, start=BASE + timedelta(minutes=5)
    )
    assert windowed.summary.trades == 2
    # Baseline unwinds only the trades inside the window: 1012 - 2 = 1010.
    assert windowed.start_balance == 1010.0


def test_baseline_is_the_real_account_balance_when_the_window_opens() -> None:
    """With an asset filter and no dates, the curve starts from the account
    balance as it really was when the first matching trade closed — the other
    asset's +100 before it is part of that balance, not of the result."""
    trades = [trade(1, 100.0, symbol="GOLD"), trade(2, 20.0, minutes=1, symbol="USTEC")]
    report = compute_performance(trades, account_balance=1120.0, symbols=["USTEC"])
    assert report.start_balance == 1100.0
    assert report.summary.net == 20.0
    assert report.end_balance == 1120.0


def test_buckets_split_by_day_week_and_month() -> None:
    trades = [
        trade(1, 10.0),  # Mon 02/03
        trade(2, -4.0, minutes=60 * 24),  # Tue 03/03
        trade(3, 6.0, minutes=60 * 24 * 10),  # Thu 12/03, next ISO week
        trade(4, 3.0, minutes=60 * 24 * 40),  # April
    ]
    report = compute_performance(trades, account_balance=1015.0)
    assert [b.key for b in report.by_day] == [
        "2026-03-02",
        "2026-03-03",
        "2026-03-12",
        "2026-04-11",
    ]
    assert [b.stats.net for b in report.by_day] == [10.0, -4.0, 6.0, 3.0]
    assert [b.balance_end for b in report.by_day] == [1010.0, 1006.0, 1012.0, 1015.0]
    assert [b.key for b in report.by_week] == ["2026-W10", "2026-W11", "2026-W15"]
    assert [b.key for b in report.by_month] == ["2026-03", "2026-04"]


def test_breakdowns_cover_symbol_source_side_weekday_and_hour() -> None:
    trades = [
        trade(1, 10.0, symbol="USTEC", source="manual", side="buy"),
        trade(2, -3.0, minutes=1, symbol="GOLD", source="bot", side="sell"),
    ]
    report = compute_performance(trades, account_balance=1007.0)
    assert [g.key for g in report.by_symbol] == ["USTEC", "GOLD"]  # best net first
    assert {g.key for g in report.by_source} == {"manual", "bot"}
    assert {g.key for g in report.by_side} == {"buy", "sell"}
    assert [g.label for g in report.by_weekday] == ["seg"]
    assert [g.key for g in report.by_hour] == ["14"]
    assert report.available_symbols == ["GOLD", "USTEC"]


def test_trade_list_is_newest_first_and_capped() -> None:
    trades = [trade(i, 1.0, minutes=i) for i in range(1, 6)]
    report = compute_performance(trades, account_balance=1005.0, trades_limit=2)
    assert [t.id for t in report.trades] == [5, 4]
    assert report.trades_returned == 2


def test_a_deposit_is_never_counted_as_result() -> None:
    """The real case that exposed this: +1,000 paid in, +25 actually traded."""
    trades = [trade(1, 10.0), trade(2, 15.0, minutes=30)]
    flows = [flow(900, 1000.0, minutes=15)]
    # Account is at 1031.77 now: it started at 6.77, made 25 and got 1,000 in.
    report = compute_performance(trades, account_balance=1031.77, cash_flows=flows)
    assert report.start_balance == 6.77
    assert report.summary.net == 25.0  # trading money only
    assert report.deposits == 1000.0
    assert report.withdrawals == 0.0
    assert report.capital == 1006.77  # start + what was paid in
    assert report.return_pct == 2.48  # 25 over 1006.77, not over 6.77
    assert report.end_balance == 1031.77
    # The deposit is its own step in the curve, with no result attached.
    assert [(p.balance, p.net, p.flow) for p in report.equity_curve] == [
        (16.77, 10.0, 0.0),
        (1016.77, 0.0, 1000.0),
        (1031.77, 15.0, 0.0),
    ]
    assert report.peak_balance == 1031.77


def test_a_withdrawal_is_reported_apart_too() -> None:
    trades = [trade(1, 20.0)]
    flows = [flow(901, -50.0, minutes=10, kind="withdrawal")]
    report = compute_performance(trades, account_balance=970.0, cash_flows=flows)
    assert report.start_balance == 1000.0
    assert report.withdrawals == 50.0
    assert report.summary.net == 20.0
    assert report.end_balance == 970.0


def test_a_deposit_outside_the_window_only_moves_the_baseline() -> None:
    trades = [trade(1, 10.0, minutes=60)]
    flows = [flow(902, 500.0, minutes=0)]  # before the window opens
    report = compute_performance(
        trades, account_balance=1510.0, cash_flows=flows, start=BASE + timedelta(minutes=30)
    )
    assert report.start_balance == 1500.0
    assert report.deposits == 0.0
    assert report.capital == 1500.0
    assert len(report.equity_curve) == 1


def test_time_in_trade_is_split_by_outcome_and_the_gap_is_measured() -> None:
    trades = [
        trade(1, 10.0, duration_s=30),
        trade(2, -5.0, minutes=10, duration_s=600),
    ]
    report = compute_performance(trades, account_balance=1005.0)
    assert report.summary.avg_win_duration_seconds == 30.0
    assert report.summary.avg_loss_duration_seconds == 600.0
    # Trade 1 closed at BASE, trade 2 opened 600s before BASE+10min → 0s gap.
    assert report.avg_time_between_trades_seconds == 0.0
