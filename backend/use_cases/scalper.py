"""Deterministic explosion-scalper entry engine (pure, testable).

The bot's *brain*: from one order-flow snapshot it decides whether to open or add
a scalp, and in which direction. All side effects (sending the order, counting
positions, cooldown, daily limits) live in the route; here we keep only pure,
unit-testable decisions, since this logic *opens real trades*.

Two entry modes, both one-directional per symbol:
- **Initial** (symbol flat) = an "explosion": the short tape window is BOTH
  strongly one-directional AND moving fast (range expansion vs the recent
  baseline). Both required — a drift that isn't moving, or a fast wiggle with no
  lean, is not a burst we chase.
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

from collections.abc import Sequence
from typing import Literal

from core.models import OrderFlowSnapshot, TapeTrade

Direction = Literal["buy", "sell"]

# Short tape window that defines "right now".
RECENT_PRINTS = 30
# Need at least this many directional prints before judging (else it's noise).
MIN_PRINTS = 12
# Initial-entry conviction: this share of the window's volume must be one side.
STRONG_FRACTION = 0.70
# Range expansion: the window's price travel must be at least this multiple of
# the recent baseline per-bar range (from live_activity) to count as a burst.
EXPANSION_MULT = 1.8
# Continuation-add conviction: a lower bar than the initial burst — we only need
# the flow to still lean in the held direction (lean = fraction − 0.5) to add.
ADD_LEAN = 0.10
# Reversal conviction: how hard the flow must lean AGAINST the held side before
# we stop-and-reverse (close the losing side). Higher than ADD_LEAN so ordinary
# chop around neutral doesn't whipsaw us in and out.
REVERSE_LEAN = 0.20


def _buy_fraction(trades: Sequence[TapeTrade]) -> tuple[float, int]:
    """Buy share of directional volume in the recent window + directional count.
    Returns (0.5, 0) when there's no directional volume (divide-by-zero guard)."""
    window = trades[-RECENT_PRINTS:]
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


def detect_explosion(snapshot: OrderFlowSnapshot) -> Direction | None:
    """Return 'buy'/'sell' if a fresh directional burst is firing, else None.

    Requires a `live_activity` baseline (to judge "fast vs normal") and a minimum
    sample of directional prints.
    """
    live = snapshot.live_activity
    if live is None or live.range_per_bar <= 0:
        return None

    buy_frac, count = _buy_fraction(snapshot.recent_trades)
    if count < MIN_PRINTS:
        return None

    window = snapshot.recent_trades[-RECENT_PRINTS:]
    prices = [t.price for t in window]
    window_range = (max(prices) - min(prices)) if prices else 0.0
    if window_range < EXPANSION_MULT * live.range_per_bar:
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
    levels: int = GRID_LEVELS,
    step_frac: float = GRID_STEP_FRAC,
) -> list[float]:
    """Limit-order prices below a buy entry (or above a sell entry), ATR-spaced.
    Empty when there's no usable range (can't size the grid)."""
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
    levels: int = GRID_LEVELS,
    step_frac: float = GRID_STEP_FRAC,
    breach_frac: float = GRID_BREACH_FRAC,
) -> float | None:
    """Price beyond which the whole grid region has failed (→ cut/reverse).
    For a buy it's below the deepest limit; for a sell, above. None if no range."""
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
    "detect_explosion",
    "decide_entry",
    "should_reverse",
    "should_open",
    "grid_levels",
    "grid_breach_price",
    "region_broken",
    "Direction",
]
