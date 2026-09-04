"""Turn a list of closed trades into the Performance report.

Pure functions over `ClosedTrade` — no I/O, no clock reads beyond the caller's
filters — so every number the Performance tab shows is unit-testable.

What is measured, in plain words:

- **hit rate** — winning trades over trades counted, in %.
- **profit factor** — every dollar won over every dollar lost.
- **payoff (risk-return in money)** — average win over average loss. Together
  with the hit rate it says whether the strategy can pay: expectancy per trade
  is also reported directly, in money.
- **drawdown** — how far the account fell below its own best point, in money
  and in % of that peak. Measured on the running ACCOUNT BALANCE, not on a
  cumulative sum from zero, so the % is the real account risk.
- **equity evolution** — the running balance after each closed trade, with
  deposits and withdrawals as their own steps (they move the balance but are
  never counted as result).
- **time in trade, winners vs losers** — the Profit report's "disposition"
  read: holding losers far longer than winners is a habit worth seeing.

Baseline: the collector pushes the account's CURRENT balance along with the
trades and the balance operations, so the balance before the window is that
current balance minus every trade net AND every deposit/withdrawal since. The
result (`summary.net`) is trading money only; money paid in is reported apart
(`deposits`) and the return % is measured over `capital` = the balance at the
start plus what was paid in, so a deposit can never look like a profit.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Literal

from core.models import (
    CashFlow,
    ClosedTrade,
    EquityCurvePoint,
    PerformanceBucket,
    PerformanceFilters,
    PerformanceGroup,
    PerformanceReport,
    PerformanceStats,
)

Source = Literal["all", "manual", "bot"]

_WEEKDAYS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# A trade nets exactly zero often enough (a scratch) that it deserves its own
# bucket instead of being counted as a loss.
_EPS = 0.005


def _avg_duration(trades: Sequence[ClosedTrade]) -> float:
    """Average time in trade, in seconds (0 for an empty set)."""
    if not trades:
        return 0.0
    return round(sum(t.duration_seconds for t in trades) / len(trades), 1)


def compute_stats(trades: Sequence[ClosedTrade]) -> PerformanceStats:
    """The core numbers for one set of trades (order matters only for the
    consecutive-win/loss streaks, which follow close time)."""
    if not trades:
        return PerformanceStats()
    ordered = sorted(trades, key=lambda t: (t.close_ts, t.id))
    wins = [t.net for t in ordered if t.net > _EPS]
    losses = [t.net for t in ordered if t.net < -_EPS]
    breakeven = len(ordered) - len(wins) - len(losses)
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    net = sum(t.net for t in ordered)
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    streak_w = streak_l = best_w = best_l = 0
    for trade in ordered:
        if trade.net > _EPS:
            streak_w += 1
            streak_l = 0
        elif trade.net < -_EPS:
            streak_l += 1
            streak_w = 0
        else:
            streak_w = streak_l = 0
        best_w = max(best_w, streak_w)
        best_l = max(best_l, streak_l)
    return PerformanceStats(
        trades=len(ordered),
        wins=len(wins),
        losses=len(losses),
        breakeven=breakeven,
        win_rate=round(100.0 * len(wins) / len(ordered), 2),
        loss_rate=round(100.0 * len(losses) / len(ordered), 2),
        net=round(net, 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        profit_factor=round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        payoff=round(avg_win / avg_loss, 2) if avg_loss > 0 else None,
        expectancy=round(net / len(ordered), 2),
        best=round(max(t.net for t in ordered), 2),
        worst=round(min(t.net for t in ordered), 2),
        lots=round(sum(t.lots for t in ordered), 2),
        commission=round(sum(t.commission for t in ordered), 2),
        swap=round(sum(t.swap for t in ordered), 2),
        avg_duration_seconds=round(sum(t.duration_seconds for t in ordered) / len(ordered), 1),
        avg_win_duration_seconds=_avg_duration([t for t in ordered if t.net > _EPS]),
        avg_loss_duration_seconds=_avg_duration([t for t in ordered if t.net < -_EPS]),
        max_consecutive_wins=best_w,
        max_consecutive_losses=best_l,
    )


def _matches(
    trade: ClosedTrade,
    start: datetime | None,
    end: datetime | None,
    symbols: set[str],
    source: Source,
) -> bool:
    if start is not None and trade.close_ts < start:
        return False
    if end is not None and trade.close_ts > end:
        return False
    if symbols and trade.symbol.upper() not in symbols:
        return False
    if source != "all" and trade.source != source:
        return False
    return True


def _bucket_key(ts: datetime, period: Literal["day", "week", "month"]) -> tuple[str, str, datetime]:
    """(key, label, slice start) for one timestamp. Weeks are ISO weeks
    (Monday-based), months calendar months. Everything in UTC."""
    day = ts.astimezone(timezone.utc)
    if period == "day":
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.strftime("%Y-%m-%d"), start.strftime("%d/%m/%Y"), start
    if period == "week":
        start = (day - timedelta(days=day.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        iso = start.isocalendar()
        return (
            f"{iso.year}-W{iso.week:02d}",
            f"semana {iso.week} ({start.strftime('%d/%m')})",
            start,
        )
    start = day.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m"), start.strftime("%m/%Y"), start


def _buckets(
    trades: Sequence[ClosedTrade],
    period: Literal["day", "week", "month"],
    start_balance: float,
) -> list[PerformanceBucket]:
    grouped: dict[str, tuple[str, datetime, list[ClosedTrade]]] = {}
    for trade in trades:
        key, label, start = _bucket_key(trade.close_ts, period)
        grouped.setdefault(key, (label, start, []))[2].append(trade)
    buckets: list[PerformanceBucket] = []
    running = start_balance
    for key in sorted(grouped):
        label, start, items = grouped[key]
        stats = compute_stats(items)
        running += stats.net
        buckets.append(
            PerformanceBucket(
                key=key,
                label=label,
                start=start,
                stats=stats,
                balance_end=round(running, 2),
            )
        )
    return buckets


def _groups(
    trades: Sequence[ClosedTrade],
    key_of: Callable[[ClosedTrade], tuple[str, str]],
    sort_by_key: bool = True,
) -> list[PerformanceGroup]:
    grouped: dict[str, tuple[str, list[ClosedTrade]]] = {}
    for trade in trades:
        key, label = key_of(trade)
        grouped.setdefault(key, (label, []))[1].append(trade)
    rows = [
        PerformanceGroup(key=key, label=grouped[key][0], stats=compute_stats(grouped[key][1]))
        for key in grouped
    ]
    if sort_by_key:
        rows.sort(key=lambda g: g.key)
    else:
        rows.sort(key=lambda g: g.stats.net, reverse=True)
    return rows


def _avg_time_between(trades: Sequence[ClosedTrade]) -> float:
    """ "TET" in the Profit report: average wait between closing one trade and
    opening the next. Negative gaps (overlapping trades) count as zero."""
    if len(trades) < 2:
        return 0.0
    gaps = [
        max(0.0, (nxt.open_ts - prev.close_ts).total_seconds())
        for prev, nxt in zip(trades, trades[1:])
    ]
    return round(sum(gaps) / len(gaps), 1)


def compute_performance(
    all_trades: Iterable[ClosedTrade],
    *,
    account_balance: float,
    cash_flows: Iterable[CashFlow] = (),
    start: datetime | None = None,
    end: datetime | None = None,
    symbols: Sequence[str] | None = None,
    source: Source = "all",
    trades_limit: int = 500,
    currency: str | None = None,
    asof: datetime | None = None,
) -> PerformanceReport:
    """Build the whole report for one filter selection.

    `all_trades` and `cash_flows` must be everything the backend holds (not
    pre-filtered): the balance baseline is derived from the trades AND the
    deposits/withdrawals that sit OUTSIDE the window too.
    """
    everything = sorted(all_trades, key=lambda t: (t.close_ts, t.id))
    flows = sorted(cash_flows, key=lambda f: (f.ts, f.id))
    wanted = {s.strip().upper() for s in (symbols or []) if s.strip()}
    selected = [t for t in everything if _matches(t, start, end, wanted, source)]

    # Balance right before the window opened: today's balance minus everything
    # that moved it since — every trade (not only the filtered ones) AND every
    # deposit/withdrawal. Without the cash flows a $1,000 deposit would read as
    # if the account had always held it, flattering the return %.
    since = start if start is not None else (selected[0].close_ts if selected else None)
    if since is None:
        banked_since = 0.0
    else:
        banked_since = sum(t.net for t in everything if t.close_ts >= since) + sum(
            f.amount for f in flows if f.ts >= since
        )
    start_balance = round(account_balance - banked_since, 2)

    window_flows = [
        f for f in flows if (since is None or f.ts >= since) and (end is None or f.ts <= end)
    ]
    deposits = round(sum(f.amount for f in window_flows if f.amount > 0), 2)
    withdrawals = round(-sum(f.amount for f in window_flows if f.amount < 0), 2)
    capital = round(start_balance + deposits, 2)

    summary = compute_stats(selected)
    # One timeline: trades and cash movements, in the order the account saw
    # them. A deposit is a step in the balance, never a result.
    events: list[tuple[datetime, float, float]] = [(t.close_ts, t.net, 0.0) for t in selected]
    events += [(f.ts, 0.0, f.amount) for f in window_flows]
    events.sort(key=lambda e: e[0])
    curve: list[EquityCurvePoint] = []
    running = start_balance
    peak = start_balance
    max_dd = 0.0
    max_dd_pct = 0.0
    for ts, net, flow in events:
        running = round(running + net + flow, 2)
        peak = max(peak, running)
        drawdown = round(max(0.0, peak - running), 2)
        drawdown_pct = round(100.0 * drawdown / peak, 2) if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
        if drawdown_pct > max_dd_pct:
            max_dd_pct = drawdown_pct
        curve.append(
            EquityCurvePoint(
                ts=ts,
                balance=running,
                peak=round(peak, 2),
                drawdown=drawdown,
                drawdown_pct=drawdown_pct,
                net=net,
                flow=flow,
            )
        )
    end_balance = running
    current_dd = curve[-1].drawdown if curve else 0.0
    current_dd_pct = curve[-1].drawdown_pct if curve else 0.0

    return PerformanceReport(
        filters=PerformanceFilters(start=start, end=end, symbols=sorted(wanted), source=source),
        summary=summary,
        start_balance=start_balance,
        end_balance=round(end_balance, 2),
        peak_balance=round(peak, 2),
        avg_time_between_trades_seconds=_avg_time_between(selected),
        deposits=deposits,
        withdrawals=withdrawals,
        capital=capital,
        cash_flows=window_flows,
        return_pct=round(100.0 * summary.net / capital, 2) if capital > 0 else 0.0,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        current_drawdown=current_dd,
        current_drawdown_pct=current_dd_pct,
        recovery_factor=round(summary.net / max_dd, 2) if max_dd > 0 else None,
        equity_curve=curve,
        by_day=_buckets(selected, "day", start_balance),
        by_week=_buckets(selected, "week", start_balance),
        by_month=_buckets(selected, "month", start_balance),
        by_symbol=_groups(selected, lambda t: (t.symbol, t.symbol), sort_by_key=False),
        by_source=_groups(selected, lambda t: (t.source, "bot" if t.source == "bot" else "manual")),
        by_side=_groups(selected, lambda t: (t.side, "compra" if t.side == "buy" else "venda")),
        by_weekday=_groups(
            selected,
            lambda t: (
                str(t.close_ts.astimezone(timezone.utc).weekday()),
                _WEEKDAYS_PT[t.close_ts.astimezone(timezone.utc).weekday()],
            ),
        ),
        by_hour=_groups(
            selected,
            lambda t: (
                f"{t.close_ts.astimezone(timezone.utc).hour:02d}",
                f"{t.close_ts.astimezone(timezone.utc).hour:02d}h UTC",
            ),
        ),
        trades=list(reversed(selected))[:trades_limit],
        trades_returned=min(len(selected), trades_limit),
        available_symbols=sorted({t.symbol for t in everything}),
        first_trade_at=everything[0].close_ts if everything else None,
        currency=currency,
        asof=asof,
    )
