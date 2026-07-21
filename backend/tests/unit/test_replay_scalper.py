"""Unit tests for the tape-replay backtester.

A synthetic recorded session drives the full pipeline (wire parse → aggregator
→ flow signal → policy) end to end: two calm footprint bars build the activity
baseline, a strongly one-sided burst then triggers the explosion entry, and the
tape either runs to the profit target (banks + re-arms) or breaks the grid
region (stop-and-reverse close). Fills are simulated; decisions are the real
code paths the live bot runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from pytest import approx

from core.enums import AssetSymbol
from use_cases.replay_scalper import ReplayParams, ScalperReplay, replay

_T0 = "2026-06-09T14:{m:02d}:{s:02d}+00:00"


def _rx(minute: int, second: int) -> str:
    return _T0.format(m=minute, s=second)


def _line(minute: int, second: int, msg: dict) -> dict:
    return {"rx": _rx(minute, second), "msg": msg}


def _book(minute: int, second: int, bid: float, ask: float) -> dict:
    return _line(
        minute,
        second,
        {
            "type": "book",
            "symbol": "USTEC",
            "asof": _rx(minute, second),
            "bids": [[bid, 1.0]],
            "asks": [[ask, 1.0]],
        },
    )


def _trades(minute: int, second: int, prints: list[tuple[int, float, float, str]]) -> dict:
    return _line(
        minute,
        second,
        {
            "type": "trades",
            "symbol": "USTEC",
            "trades": [
                {"at": _rx(minute, s), "price": p, "volume": v, "side": side}
                for s, p, v, side in prints
            ],
        },
    )


def _calm_bars() -> list[dict]:
    """Two completed 1-minute bars of quiet two-sided tape (range 0.4 each) —
    the live-activity baseline the burst is judged against."""
    return [
        _book(0, 0, 100.0, 100.2),
        _trades(0, 5, [(1, 100.0, 1.0, "buy"), (2, 100.4, 1.0, "sell")]),
        _trades(1, 5, [(1, 100.0, 1.0, "buy"), (2, 100.4, 1.0, "sell")]),
    ]


def _burst() -> dict:
    """Twelve big buy prints climbing 100 → 105.5: >70% buy volume AND range
    far beyond the 0.4/bar baseline — the initial explosion."""
    prints = [(10 + k, 100.0 + 0.5 * k, 5.0, "buy") for k in range(12)]
    return _trades(2, 30, prints)


def _params(**over) -> ReplayParams:
    defaults = dict(
        profit_target=10.0,
        loss_stop=900.0,
        lots={AssetSymbol.USTEC: 2.0},
        usd_per_point={AssetSymbol.USTEC: 1.0},
    )
    defaults.update(over)
    return ReplayParams(**defaults)


def test_explosion_entry_then_profit_target_banks_and_rearms() -> None:
    sim = ScalperReplay(_params())
    for record in _calm_bars():
        sim.feed(record)
    sim.feed(_burst())
    assert sim.positions[AssetSymbol.USTEC], "explosion should have opened a position"
    entry = sim.positions[AssetSymbol.USTEC][0]
    assert entry.side == "buy" and entry.entry == 100.2  # market buy fills at the ask

    # Price runs: floating (106.5-100.2)*2 = +12.6 >= target 10 → bank + re-arm.
    sim.feed(_book(2, 40, 106.5, 106.7))
    report = sim.finish()

    assert not sim.positions[AssetSymbol.USTEC]
    assert sim.flattening  # re-arm cooldown, not disarmed
    (close,) = report.closes
    assert (close.scope, close.reason) == ("ACCOUNT", "target")
    assert close.pnl == approx(12.6)
    assert report.total_pnl == approx(12.6)
    assert report.entries == 1 and report.wins == 1 and not report.halted


def test_grid_region_break_closes_as_reverse() -> None:
    sim = ScalperReplay(_params())
    for record in _calm_bars():
        sim.feed(record)
    sim.feed(_burst())
    # Grid region: step = 0.5*rpb(0.4) = 0.2, breach = 100.2 − 0.2*3.5 = 99.5.
    # Book mid 99.1 < 99.5 → the whole region failed → close (reverse).
    sim.feed(_book(2, 40, 99.0, 99.2))
    report = sim.finish()

    (close,) = report.closes
    assert (close.scope, close.reason) == ("USTEC", "reverse")
    assert close.pnl == approx((99.0 - 100.2) * 2.0)  # long closes on the bid
    assert report.losses == 1


def test_grid_limits_fill_on_prints_through_the_level() -> None:
    sim = ScalperReplay(_params())
    for record in _calm_bars():
        sim.feed(record)
    sim.feed(_burst())
    # Limits sit at 100.0 / 99.8 / 99.6. A pullback print at 99.9 crosses only
    # the first level, which fills AT ITS LIMIT PRICE (100.0, not 99.9).
    sim.feed(_trades(2, 45, [(45, 99.9, 1.0, "sell")]))
    entries = sim.positions[AssetSymbol.USTEC]
    assert [p.entry for p in entries] == approx([100.2, 100.0])
    assert len(sim.pending[AssetSymbol.USTEC]) == 2


def test_replay_reads_jsonl_files(tmp_path: Path) -> None:
    tape = tmp_path / "tape-2026-06-09.jsonl"
    records = _calm_bars() + [_burst(), _book(2, 40, 106.5, 106.7)]
    tape.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    report = replay([tape], _params())
    assert report.total_pnl == approx(12.6)
    assert report.events == len(records)


def test_thin_session_blocks_the_entry() -> None:
    sim = ScalperReplay(_params())
    for record in _calm_bars():
        sim.feed(record)
    sim.feed(
        _line(
            2,
            0,
            {
                "type": "liquidity",
                "symbol": "USTEC",
                "asof": _rx(2, 0),
                "realized_volume": 10.0,
                "baseline_volume": 100.0,
                "ratio": 0.1,
                "sample_days": 20,
            },
        )
    )
    sim.feed(_burst())
    assert not sim.positions[AssetSymbol.USTEC]
    assert sim.finish().entries == 0
