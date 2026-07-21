"""Parameter sweep for the explosion scalper over a recorded tape.

Runs the replay backtest (`replay_scalper`) once per combination of a value
grid, looking for a ROBUST REGION rather than a single lucky optimum: besides
the ranked runs, `axis_summary` averages P&L per individual value across every
combination it appears in — a value that only wins in one specific combo is
curve-fitting, a value whose whole row is healthy is a region.

Axis naming convention:
- UPPERCASE names are `use_cases/scalper.py` tuning constants, applied via
  `scalper.tuned()` (e.g. STRONG_FRACTION, EXPANSION_MULT, REVERSE_LEAN).
- lowercase names are `ReplayParams` fields (e.g. profit_target,
  symbol_stop_usd).

Sweeps mutate the scalper module's globals while a run executes (restored after
each run) — never run one in the same process as a live armed bot.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from itertools import product
from typing import Any

from use_cases import scalper
from use_cases.replay_scalper import ReplayParams, ReplayReport, ScalperReplay

# The starting grid when the CLI gets no --set axes: the entry conviction, the
# burst threshold, the reverse trigger and the new per-symbol stop — the four
# knobs most likely to separate edge from noise. 81 replays.
DEFAULT_GRID: dict[str, list[float]] = {
    "STRONG_FRACTION": [0.65, 0.70, 0.75],
    "EXPANSION_MULT": [1.5, 1.8, 2.2],
    "REVERSE_LEAN": [0.15, 0.20, 0.25],
    "symbol_stop_usd": [0.0, 150.0, 300.0],
}

_PARAM_FIELDS = {f.name for f in fields(ReplayParams)}


@dataclass
class SweepRun:
    """One grid point: the overrides applied and the resulting report."""

    overrides: dict[str, float]
    report: ReplayReport


def _run_one(
    records: list[dict[str, Any]], overrides: dict[str, float], base: ReplayParams
) -> ReplayReport:
    consts = {k: v for k, v in overrides.items() if k.isupper()}
    param_fields = {k: v for k, v in overrides.items() if not k.isupper()}
    # replace() is typed per-field; a swept mapping is dynamic by nature.
    params = replace(base, **param_fields)  # type: ignore[arg-type]
    with scalper.tuned(**consts):
        sim = ScalperReplay(params)
        for record in records:
            sim.feed(record)
        return sim.finish()


def sweep(
    records: list[dict[str, Any]],
    grid: dict[str, list[float]],
    base: ReplayParams | None = None,
) -> list[SweepRun]:
    """Replay `records` once per grid combination; ranked best P&L first.

    Unknown axis names fail fast (lowercase must be a ReplayParams field;
    uppercase is validated by `scalper.tuned`). `records` is the pre-loaded
    tape (list of {"rx", "msg"} dicts) so the JSONL is read only once.
    """
    bad = [n for n in grid if not n.isupper() and n not in _PARAM_FIELDS]
    if bad:
        raise ValueError(f"unknown ReplayParams field(s): {', '.join(bad)}")
    base = base or ReplayParams()
    names = list(grid)
    runs = [
        SweepRun(
            overrides=dict(zip(names, combo)),
            report=_run_one(records, dict(zip(names, combo)), base),
        )
        for combo in product(*(grid[n] for n in names))
    ]
    # Best P&L first; equal P&L prefers the shallower drawdown.
    runs.sort(key=lambda r: (-r.report.total_pnl, r.report.max_drawdown))
    return runs


def axis_summary(runs: list[SweepRun]) -> dict[str, dict[float, float]]:
    """Mean P&L per individual axis value across every combo it appears in.

    The robustness read: a healthy MEAN says the value works across the rest of
    the grid; a value that only spikes in one combo does not move its mean much.
    """
    sums: dict[str, dict[float, list[float]]] = {}
    for run in runs:
        for name, value in run.overrides.items():
            sums.setdefault(name, {}).setdefault(value, []).append(run.report.total_pnl)
    return {
        name: {value: sum(pnls) / len(pnls) for value, pnls in values.items()}
        for name, values in sums.items()
    }


__all__ = ["DEFAULT_GRID", "SweepRun", "sweep", "axis_summary"]
