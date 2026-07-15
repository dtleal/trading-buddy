"""Unit tests for the consolidated per-symbol flow signal.

The signal must be DERIVED from the existing scalper/assess logic (single
source of truth), so beyond the behavioral cases the key tests here are the
agreement sweeps: on the same inputs, the signal's entry direction must equal
`decide_entry` and its bot-grade exit must equal `should_reverse` — proving
the signal shown on the UI can never diverge from what the armed bot does.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.enums import AssetSymbol
from core.models import LiveActivity, OrderFlowSnapshot, Position, TapeTrade
from use_cases.assess_trade_signals import assess_trade_signals
from use_cases.scalper import decide_entry, should_reverse
from use_cases.trade_signal import (
    compute_flow_signal,
    held_side,
    signal_entry_direction,
    signal_says_reverse,
)

_AT = datetime(2026, 6, 9, 14, 0, 0, tzinfo=timezone.utc)


def _trades(buys: int, sells: int, *, window_range: float = 10.0) -> list[TapeTrade]:
    sides = ["buy"] * buys + ["sell"] * sells
    n = len(sides)
    # Spread prints across 60s (== the baseline interval) so the burst detector's
    # speed-scaled expansion test reduces to `window_range vs EXPANSION_MULT *
    # range_per_bar` — the per-bar contract these cases assume.
    return [
        TapeTrade(
            symbol=AssetSymbol.USTEC,
            at=_AT + timedelta(seconds=60.0 * i / (n - 1)) if n > 1 else _AT,
            # Alternate lo/hi so the window's price travel == window_range.
            price=100.0 if i % 2 == 0 else 100.0 + window_range,
            volume=1.0,
            side=s,  # type: ignore[arg-type]
        )
        for i, s in enumerate(sides)
    ]


def _snap(
    buys: int,
    sells: int,
    *,
    window_range: float = 10.0,
    range_per_bar: float | None = 2.0,
    trades: list[TapeTrade] | None = None,
) -> OrderFlowSnapshot:
    live = (
        None
        if range_per_bar is None
        else LiveActivity(
            range_per_bar=range_per_bar, volume_per_bar=10.0, interval_seconds=60, sampled_bars=5
        )
    )
    return OrderFlowSnapshot(
        symbol=AssetSymbol.USTEC,
        asof=_AT,
        recent_trades=trades if trades is not None else _trades(buys, sells, window_range=window_range),
        live_activity=live,
    )


def _pos(side: str, *, ticket: int = 1, profit: float = 0.0) -> Position:
    return Position(
        symbol=AssetSymbol.USTEC,
        ticket=ticket,
        side=side,  # type: ignore[arg-type]
        volume=1.0,
        price_open=100.0,
        price_current=100.0,
        profit=profit,
        seconds_open=5.0,
    )


# --- flat: entry from the explosion logic -------------------------------------


def test_flat_buy_explosion_enters_long() -> None:
    sig = compute_flow_signal(_snap(20, 3), [])
    assert sig.action == "enter_long"
    assert sig.basis == "explosion"
    assert 0.0 < sig.strength <= 1.0
    assert signal_entry_direction(sig) == "buy"


def test_flat_sell_explosion_enters_short() -> None:
    sig = compute_flow_signal(_snap(3, 20), [])
    assert sig.action == "enter_short"
    assert sig.basis == "explosion"
    assert signal_entry_direction(sig) == "sell"


def test_flat_neutral_flow_holds() -> None:
    sig = compute_flow_signal(_snap(12, 12), [])
    assert sig.action == "hold" and sig.basis == "none"
    assert signal_entry_direction(sig) is None


def test_flat_directional_without_expansion_holds() -> None:
    # Strong lean but the window isn't moving fast → not a burst → hold.
    sig = compute_flow_signal(_snap(20, 3, window_range=3.0, range_per_bar=2.0), [])
    assert sig.action == "hold"


def test_flat_too_few_prints_holds() -> None:
    sig = compute_flow_signal(_snap(5, 5), [])
    assert sig.action == "hold"


def test_flat_no_baseline_holds() -> None:
    sig = compute_flow_signal(_snap(20, 3, range_per_bar=None), [])
    assert sig.action == "hold"


# --- holding: exit half --------------------------------------------------------


def test_reverse_grade_exit_when_flow_flips_hard() -> None:
    # Long + strong sell flow → the bot-grade stop-and-reverse exit.
    sig = compute_flow_signal(_snap(3, 17), [_pos("buy")])
    assert sig.action == "exit" and sig.basis == "reversal"
    assert signal_says_reverse(sig) is True
    # Mirror: short + strong buy flow.
    sig2 = compute_flow_signal(_snap(17, 3), [_pos("sell")])
    assert sig2.action == "exit" and sig2.basis == "reversal"


def test_against_exit_is_advisory_not_bot_grade() -> None:
    # Recent 30 prints only mildly against (13/17 → 0.067 < REVERSE_LEAN), but
    # the 50-window is clearly against (13 buys / 37 sells → lean −0.24).
    trades = _trades(0, 20) + _trades(13, 17)
    sig = compute_flow_signal(_snap(0, 0, trades=trades), [_pos("buy")])
    assert sig.action == "exit" and sig.basis == "against"
    assert signal_says_reverse(sig) is False  # bot does NOT act on this
    # Sanity: the scalper itself would not reverse here.
    assert should_reverse(_snap(0, 0, trades=trades), "buy") is False


def test_exhaustion_exit_when_in_profit_and_momentum_stalls() -> None:
    # Neutral flow + profit → the take-profit nudge, advisory only.
    sig = compute_flow_signal(_snap(15, 15), [_pos("buy", profit=25.0)])
    assert sig.action == "exit" and sig.basis == "exhaustion"
    assert signal_says_reverse(sig) is False
    assert 0.0 <= sig.strength <= 1.0


def test_no_exhaustion_without_profit() -> None:
    sig = compute_flow_signal(_snap(15, 15), [_pos("buy", profit=-5.0)])
    assert sig.action == "hold"


def test_continuation_lean_supports_held_side() -> None:
    # Holding sells, flow still leans sell without a fresh burst → enter_short
    # (continuation) — matches decide_entry's add read.
    snap = _snap(3, 17, window_range=2.0, range_per_bar=10.0)  # no expansion
    sig = compute_flow_signal(snap, [_pos("sell")])
    assert sig.action == "enter_short" and sig.basis == "lean"
    assert decide_entry(snap, current_side="sell", open_on_symbol=1) == "sell"


def test_ambiguous_hedged_position_holds() -> None:
    # Long + short on the same symbol → no judgeable side → hold, like the bot.
    sig = compute_flow_signal(_snap(20, 3), [_pos("buy", ticket=1), _pos("sell", ticket=2)])
    assert sig.action == "hold"
    assert held_side([_pos("buy", ticket=1), _pos("sell", ticket=2)]) is None


def test_reverse_preempts_softer_exits() -> None:
    # Strong flip + in profit: the reversal wins over exhaustion/against.
    sig = compute_flow_signal(_snap(3, 17), [_pos("buy", profit=50.0)])
    assert sig.basis == "reversal"


# --- agreement sweeps: the signal can never diverge from the scalper ----------


def test_flat_entry_agrees_with_decide_entry_everywhere() -> None:
    """For a grid of tape mixes and range regimes, the signal's entry direction
    when flat is EXACTLY decide_entry(open_on_symbol=0) — both ways (iff)."""
    for buys in range(0, 31, 2):
        for sells in range(0, 31, 2):
            for window_range, rpb in ((10.0, 2.0), (3.0, 2.0), (10.0, None)):
                snap = _snap(buys, sells, window_range=window_range, range_per_bar=rpb)
                expected = decide_entry(snap, current_side=None, open_on_symbol=0)
                got = signal_entry_direction(compute_flow_signal(snap, []))
                assert got == expected, (buys, sells, window_range, rpb)


def test_reverse_exit_agrees_with_should_reverse_everywhere() -> None:
    """For a grid of tape mixes, the signal's bot-grade exit while holding is
    EXACTLY should_reverse — both ways (iff), for both held sides."""
    for buys in range(0, 31, 2):
        for sells in range(0, 31, 2):
            snap = _snap(buys, sells)
            for side in ("buy", "sell"):
                sig = compute_flow_signal(snap, [_pos(side)])
                assert signal_says_reverse(sig) == should_reverse(snap, side), (
                    buys,
                    sells,
                    side,
                )


def test_against_exit_agrees_with_assess_alert() -> None:
    """When the signal downgrades to the softer 'against' exit, the existing
    per-position assess alert fires too — same evidence, same thresholds."""
    trades = _trades(0, 20) + _trades(13, 17)
    snap = _snap(0, 0, trades=trades)
    pos = _pos("buy")
    sig = compute_flow_signal(snap, [pos])
    alerts = assess_trade_signals(snap, [pos])
    assert sig.basis == "against"
    assert alerts and alerts[0].code == "pressure_against"


def test_strength_always_within_bounds() -> None:
    for buys in range(0, 25, 3):
        for sells in range(0, 25, 3):
            snap = _snap(buys, sells)
            for positions in ([], [_pos("buy", profit=10.0)], [_pos("sell", profit=-10.0)]):
                sig = compute_flow_signal(snap, positions)
                assert 0.0 <= sig.strength <= 1.0
