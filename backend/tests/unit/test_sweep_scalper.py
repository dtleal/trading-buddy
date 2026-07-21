"""Unit tests for the parameter-sweep harness and the `tuned()` override.

The sweep drives real replays, so the synthetic tape from the replay tests is
reused: a baseline + burst that enters long, then a book move that decides the
outcome. What is pinned: tuned() actually changes decisions AND restores the
globals, sweeps rank/aggregate correctly, and unknown axes fail fast.
"""

from __future__ import annotations

import pytest
from pytest import approx

from core.enums import AssetSymbol
from tests.unit.test_replay_scalper import _book, _burst, _calm_bars, _params
from use_cases import scalper
from use_cases.replay_scalper import ScalperReplay
from use_cases.sweep_scalper import axis_summary, sweep


def _tape_to_target() -> list[dict]:
    """Calm baseline → buy burst → price runs to the profit target."""
    return _calm_bars() + [_burst(), _book(2, 40, 106.5, 106.7)]


def test_tuned_overrides_and_restores() -> None:
    before = scalper.STRONG_FRACTION
    with scalper.tuned(STRONG_FRACTION=0.99):
        assert scalper.STRONG_FRACTION == 0.99
    assert scalper.STRONG_FRACTION == before


def test_tuned_rejects_unknown_names() -> None:
    with pytest.raises(ValueError, match="TYPO_CONSTANT"):
        with scalper.tuned(TYPO_CONSTANT=1.0):
            pass


def test_tuned_reaches_grid_defaults_at_call_time() -> None:
    # `levels=None` resolves against the module global, so tuned() reaches it.
    with scalper.tuned(GRID_LEVELS=1):
        assert len(scalper.grid_levels(100.0, "buy", 0.4)) == 1
    assert len(scalper.grid_levels(100.0, "buy", 0.4)) == 3


def test_symbol_stop_cuts_the_position() -> None:
    sim = ScalperReplay(_params(symbol_stop_usd=1.5))
    for record in _calm_bars():
        sim.feed(record)
    sim.feed(_burst())  # long 2.0 lots @100.2
    sim.feed(_book(2, 40, 99.4, 99.6))  # −1.6 USD floating ≤ −1.5 → hard stop
    report = sim.finish()

    (close,) = report.closes
    assert (close.scope, close.reason) == ("USTEC", "stop")
    assert close.pnl == approx(-1.6)


def test_sweep_ranks_and_aggregates() -> None:
    records = _tape_to_target()
    # STRONG_FRACTION 0.70 enters (burst is ~97% buy volume ≥ 0.70) and banks
    # +12.6; 1.01 is unreachable (fraction can never exceed 1.0) → no entry.
    runs = sweep(records, {"STRONG_FRACTION": [1.01, 0.70]}, base=_params())

    assert [r.overrides["STRONG_FRACTION"] for r in runs] == [0.70, 1.01]
    assert runs[0].report.total_pnl == approx(12.6)
    assert runs[1].report.total_pnl == 0.0 and runs[1].report.entries == 0
    assert scalper.STRONG_FRACTION == 0.70  # restored after the sweep

    means = axis_summary(runs)["STRONG_FRACTION"]
    assert means[0.70] == approx(12.6) and means[1.01] == 0.0


def test_sweep_mixes_constants_and_replay_params() -> None:
    records = _tape_to_target()
    runs = sweep(
        records,
        {"STRONG_FRACTION": [0.70], "symbol_stop_usd": [0.0, 1000.0]},
        base=_params(),
    )
    # Stop=1000 never triggers on a +12.6 move, so both land on the target.
    assert all(r.report.total_pnl == approx(12.6) for r in runs)
    assert {r.overrides["symbol_stop_usd"] for r in runs} == {0.0, 1000.0}


def test_sweep_rejects_unknown_param_field() -> None:
    with pytest.raises(ValueError, match="not_a_field"):
        sweep([], {"not_a_field": [1.0]})
