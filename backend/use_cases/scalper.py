"""Deterministic explosion-scalper entry engine (pure, testable).

The bot's *brain*: from one order-flow snapshot it decides whether to open or add
a scalp, and in which direction. All side effects (sending the order, counting
positions, cooldown, daily limits) live in the route; here we keep only pure,
unit-testable decisions, since this logic *opens real trades*.

Two entry modes, both one-directional per symbol:
- **Initial** (symbol flat) = an "explosion": the recent tape window (a rolling
  span of seconds, not a fixed print count) is BOTH strongly one-directional AND
  moving fast (range expansion vs the recent baseline, judged as travel-per-time
  so a burst that builds over a minute still counts). Both required — a drift
  that isn't moving, or a fast wiggle with no lean, is not a burst we chase.
- **Continuation add** (already holding) = keep adding *in the same direction*
  while the flow still leans that way. This does NOT require a fresh range
  explosion (the baseline rises with the move and would suppress re-triggers), so
  the position scales up through a sustained run instead of opening just once.

Direction consistency is enforced here: while holding one side we NEVER signal
the opposite — no accidental long+short hedge on the same symbol.

EDGE WARNING: on synthesized-tick CFD feeds this is a noisy proxy. The constants
below are starting points to TUNE on demo, not a validated edge.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import timedelta
from typing import Literal

from core.models import OrderFlowSnapshot, TapeTrade

Direction = Literal["buy", "sell"]

# Count-based window for the directional lean behind the continuation-add and
# the stop-and-reverse: "the recent prints" right now. Kept a fixed COUNT (not
# time) so those two reads stay exactly as the original engine tuned them.
RECENT_PRINTS = 30
# Time window (seconds) for the INITIAL burst detection ONLY. Sliced by
# timestamp, never by a fixed print COUNT: on a fast feed (hundreds of prints/
# min) a fixed count is only a few seconds wide and cannot see a burst that
# unfolds over a minute — the reason a big multi-minute candle slipped past the
# old detector. Capped in practice by the tape's own length (see `tape_maxlen`).
WINDOW_SECONDS = 90.0
# Floor for the burst window's measured span when scaling the baseline (below).
# Guards the divide when the whole window landed within a heartbeat of prints.
MIN_SPAN_SECONDS = 10.0
# Need at least this many directional prints before judging (else it's noise).
MIN_PRINTS = 12
# Initial-entry conviction: this share of the window's volume must be one side.
STRONG_FRACTION = 0.70
# Range expansion judged as SPEED: the window's price travel must be at least
# this multiple of the NORMAL travel for the same elapsed time — range_per_bar
# scaled from its interval down to the window's actual span (from live_activity).
# Comparing travel-per-time (not raw travel) makes the test independent of tick
# rate and window length, so a move that unfolds over a minute still registers.
EXPANSION_MULT = 1.8
# Continuation-add conviction: a lower bar than the initial burst — we only need
# the flow to still lean in the held direction (lean = fraction − 0.5) to add.
ADD_LEAN = 0.10
# Reversal conviction: how hard the flow must lean AGAINST the held side before
# we stop-and-reverse (close the losing side). Higher than ADD_LEAN so ordinary
# chop around neutral doesn't whipsaw us in and out.
REVERSE_LEAN = 0.20

# --- execution policy (shared by the live bot route AND the tape replay) -----
# These gate/manage real entries in `api/routes/orderflow.py::_run_bot`; they
# live here so the backtest replays the exact same policy without re-declaring
# a threshold.
# Session is thin (skip entries) when realized participation is below this
# share of the same-time-of-day baseline — matches the dashboard's "thin" gate.
THIN_RATIO = 0.75
# After banking a win we wait for positions to flatten AND this long before the
# bot opens again, so it doesn't immediately re-enter the exhausted move.
REARM_COOLDOWN_S = 5.0
# Trailing profit lock (per symbol): once a symbol's unrealized gain has peaked
# at >= LOCK_MIN_USD, close it if it gives back more than LOCK_GIVEBACK of that
# peak while still positive — banks the move instead of round-tripping back to
# breakeven (the "perfect short that came all the way back" case).
LOCK_MIN_USD = 40.0
LOCK_GIVEBACK = 0.40
# Per-symbol hard stop: close a symbol when its floating P&L reaches −this many
# USD — the per-trade risk cap the grid breach alone can't give (a breach is
# price-based; this caps the DOLLAR damage of a scaled-in position that keeps
# leaning). 0 disables it, which is the live default until a swept value proves
# itself on recorded tape.
SYMBOL_STOP_USD = 0.0


def symbol_stopped(sym_pnl: float, stop_usd: float) -> bool:
    """True when a symbol's floating loss has hit the per-symbol hard stop.
    Disabled (always False) when `stop_usd` is 0 or negative."""
    return stop_usd > 0 and sym_pnl <= -stop_usd


@contextmanager
def tuned(**overrides: float) -> Iterator[None]:
    """Temporarily override tuning constants by NAME (e.g. STRONG_FRACTION=0.6).

    For backtest parameter sweeps ONLY — never call while a live bot is armed:
    the live route reads these same globals mid-tick. Values are restored on
    exit even if the body raises. Unknown names are rejected so a typo can't
    silently sweep nothing.
    """
    module = sys.modules[__name__]
    unknown = [n for n in overrides if not (n.isupper() and hasattr(module, n))]
    if unknown:
        raise ValueError(f"unknown tuning constant(s): {', '.join(unknown)}")
    saved = {name: getattr(module, name) for name in overrides}
    for name, value in overrides.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(module, name, value)


def _recent_window(trades: Sequence[TapeTrade], seconds: float) -> list[TapeTrade]:
    """The tail of `trades` printed within `seconds` of the latest print.

    A real span of market time, not a fixed print count (see WINDOW_SECONDS).
    The tape is time-ordered, so this is the trailing slice at/after the cutoff.
    Empty in, empty out. Used by the burst detector only.
    """
    if not trades:
        return []
    cutoff = trades[-1].at - timedelta(seconds=seconds)
    return [t for t in trades if t.at >= cutoff]


def _directional_fraction(window: Sequence[TapeTrade]) -> tuple[float, int]:
    """Buy share of directional volume in `window` + directional print count.
    Returns (0.5, 0) when there's no directional volume (divide-by-zero guard)."""
    buy = sell = 0.0
    count = 0
    for t in window:
        if t.side == "buy":
            buy += t.volume
            count += 1
        elif t.side == "sell":
            sell += t.volume
            count += 1
    total = buy + sell
    if total <= 0:
        return 0.5, count
    return buy / total, count


def _buy_fraction(trades: Sequence[TapeTrade]) -> tuple[float, int]:
    """Buy share + count over the last RECENT_PRINTS (the continuation-add and
    stop-and-reverse lean). The burst detector uses a time window instead."""
    return _directional_fraction(trades[-RECENT_PRINTS:])


def detect_explosion(snapshot: OrderFlowSnapshot) -> Direction | None:
    """Return 'buy'/'sell' if a fresh directional burst is firing, else None.

    Requires a `live_activity` baseline (to judge "fast vs normal") and a minimum
    sample of directional prints.
    """
    live = snapshot.live_activity
    if live is None or live.range_per_bar <= 0 or live.interval_seconds <= 0:
        return None

    window = _recent_window(snapshot.recent_trades, WINDOW_SECONDS)
    buy_frac, count = _directional_fraction(window)
    if count < MIN_PRINTS:
        return None

    prices = [t.price for t in window]
    window_range = (max(prices) - min(prices)) if prices else 0.0
    # Scale the per-bar baseline down to the window's ACTUAL elapsed span, so we
    # compare like-for-like travel-per-time (not a full bar's travel against a
    # sub-bar window). A move stretched over the whole span now counts as a
    # burst if it's moving ≥ EXPANSION_MULT× faster than normal for that time.
    span = max((window[-1].at - window[0].at).total_seconds(), MIN_SPAN_SECONDS)
    baseline_travel = live.range_per_bar * (span / live.interval_seconds)
    if window_range < EXPANSION_MULT * baseline_travel:
        return None

    if buy_frac >= STRONG_FRACTION:
        return "buy"
    if (1.0 - buy_frac) >= STRONG_FRACTION:
        return "sell"
    return None


def decide_entry(
    snapshot: OrderFlowSnapshot,
    *,
    current_side: Direction | None,
    open_on_symbol: int,
) -> Direction | None:
    """The direction to open/add for one symbol, or None.

    - Flat (`open_on_symbol == 0`) → require a full explosion (initial entry).
    - Holding a side → add in THAT side while the flow still leans it (>= ADD_LEAN).
      Never the opposite (no hedge); never when the held side is ambiguous.

    Cap / cooldown / liquidity gating is applied separately by `should_open`.
    """
    if open_on_symbol == 0:
        return detect_explosion(snapshot)
    if current_side is None:
        return None  # holding but side ambiguous (tie) → don't add
    buy_frac, count = _buy_fraction(snapshot.recent_trades)
    if count < MIN_PRINTS:
        return None
    lean = (buy_frac - 0.5) if current_side == "buy" else (0.5 - buy_frac)
    return current_side if lean >= ADD_LEAN else None


# Grid / market-maker entry: one market order + this many limit orders spaced
# below (buy) / above (sell) the entry, each step = GRID_STEP_FRAC × the recent
# per-bar range (an ATR proxy). The "region floor" is the deepest level plus a
# GRID_BREACH_FRAC buffer; price beyond it means the whole region failed → cut.
GRID_LEVELS = 3
GRID_STEP_FRAC = 0.5
GRID_BREACH_FRAC = 0.5


def grid_levels(
    entry: float,
    side: Direction,
    range_per_bar: float,
    *,
    levels: int | None = None,
    step_frac: float | None = None,
) -> list[float]:
    """Limit-order prices below a buy entry (or above a sell entry), ATR-spaced.
    Empty when there's no usable range (can't size the grid). None params fall
    back to the module constants AT CALL TIME so `tuned()` sweeps reach them
    (a `= GRID_LEVELS` default would freeze the value at import)."""
    levels = GRID_LEVELS if levels is None else levels
    step_frac = GRID_STEP_FRAC if step_frac is None else step_frac
    step = range_per_bar * step_frac
    if step <= 0:
        return []
    sign = -1.0 if side == "buy" else 1.0
    return [entry + sign * step * (k + 1) for k in range(levels)]


def grid_breach_price(
    entry: float,
    side: Direction,
    range_per_bar: float,
    *,
    levels: int | None = None,
    step_frac: float | None = None,
    breach_frac: float | None = None,
) -> float | None:
    """Price beyond which the whole grid region has failed (→ cut/reverse).
    For a buy it's below the deepest limit; for a sell, above. None if no range.
    None params fall back to the module constants at call time (see grid_levels)."""
    levels = GRID_LEVELS if levels is None else levels
    step_frac = GRID_STEP_FRAC if step_frac is None else step_frac
    breach_frac = GRID_BREACH_FRAC if breach_frac is None else breach_frac
    step = range_per_bar * step_frac
    if step <= 0:
        return None
    sign = -1.0 if side == "buy" else 1.0
    return entry + sign * step * (levels + breach_frac)


def region_broken(price: float, side: Direction, breach_price: float) -> bool:
    """True when `price` has broken past the grid region (failed) for the side."""
    return price < breach_price if side == "buy" else price > breach_price


def should_reverse(snapshot: OrderFlowSnapshot, current_side: Direction) -> bool:
    """True when the flow has flipped strongly AGAINST the held side — the signal
    to close that side (stop & reverse). Uses REVERSE_LEAN (> ADD_LEAN) so noise
    around neutral doesn't whipsaw; needs a minimum sample of directional prints.
    """
    buy_frac, count = _buy_fraction(snapshot.recent_trades)
    if count < MIN_PRINTS:
        return False
    against = (0.5 - buy_frac) if current_side == "buy" else (buy_frac - 0.5)
    return against >= REVERSE_LEAN


def should_open(
    *,
    direction: Direction | None,
    open_on_symbol: int,
    max_per_symbol: int,
    cooldown_ok: bool,
    daily_halted: bool,
    liquidity_ok: bool = True,
) -> bool:
    """Gate one entry. Pure so every refusal reason is unit-testable.

    Opens only when there's a direction, the session isn't thin (`liquidity_ok`),
    we're under the per-symbol position cap, the post-trade cooldown has elapsed,
    and the day isn't halted (loss limit).
    """
    if direction is None:
        return False
    if daily_halted:
        return False
    if not liquidity_ok:
        return False
    if not cooldown_ok:
        return False
    if open_on_symbol >= max_per_symbol:
        return False
    return True


__all__ = [
    "THIN_RATIO",
    "REARM_COOLDOWN_S",
    "LOCK_MIN_USD",
    "LOCK_GIVEBACK",
    "SYMBOL_STOP_USD",
    "symbol_stopped",
    "tuned",
    "detect_explosion",
    "decide_entry",
    "should_reverse",
    "should_open",
    "grid_levels",
    "grid_breach_price",
    "region_broken",
    "Direction",
]
