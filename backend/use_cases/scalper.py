"""Deterministic explosion-scalper entry engine (pure, testable).

The bot's *brain*: from one order-flow snapshot it decides whether a fresh
"explosion" (a fast, one-sided burst) is happening and in which direction. All
orchestration that has side effects — sending the open order, counting open
positions, cooldown, daily limits — lives in the route; here we keep only pure,
unit-testable decisions so the logic that *opens real trades* is pinned down.

An explosion = the short tape window is BOTH strongly one-directional AND moving
fast (range expansion vs the recent baseline). Both are required: a one-sided
drift that isn't moving, or a fast wiggle with no directional lean, is not a
burst we want to chase.

EDGE WARNING: on synthesized-tick CFD feeds this is a noisy proxy. The constants
below are starting points to TUNE on demo, not a validated edge.
"""

from __future__ import annotations

from typing import Literal

from core.models import OrderFlowSnapshot

Direction = Literal["buy", "sell"]

# Short tape window that defines "right now".
RECENT_PRINTS = 30
# Need at least this many directional prints before judging (else it's noise).
MIN_PRINTS = 12
# Directional conviction: this share of the window's volume must be one side.
STRONG_FRACTION = 0.70
# Range expansion: the window's price travel must be at least this multiple of
# the recent baseline per-bar range (from live_activity) to count as a burst.
EXPANSION_MULT = 1.8


def detect_explosion(snapshot: OrderFlowSnapshot) -> Direction | None:
    """Return 'buy'/'sell' if a fresh directional burst is firing, else None.

    Requires a `live_activity` baseline (so we can judge "fast vs normal") and a
    minimum sample of directional prints.
    """
    live = snapshot.live_activity
    if live is None or live.range_per_bar <= 0:
        return None

    window = snapshot.recent_trades[-RECENT_PRINTS:]
    buy = sell = 0.0
    count = 0
    lo = hi = None
    for t in window:
        if t.side == "buy":
            buy += t.volume
            count += 1
        elif t.side == "sell":
            sell += t.volume
            count += 1
        lo = t.price if lo is None else min(lo, t.price)
        hi = t.price if hi is None else max(hi, t.price)
    if count < MIN_PRINTS:
        return None

    total = buy + sell
    if total <= 0:
        return None
    buy_frac = buy / total

    # Range expansion vs the recent per-bar baseline.
    window_range = (hi - lo) if (lo is not None and hi is not None) else 0.0
    if window_range < EXPANSION_MULT * live.range_per_bar:
        return None

    if buy_frac >= STRONG_FRACTION:
        return "buy"
    if (1.0 - buy_frac) >= STRONG_FRACTION:
        return "sell"
    return None


def should_open(
    *,
    direction: Direction | None,
    open_on_symbol: int,
    max_per_symbol: int,
    cooldown_ok: bool,
    daily_halted: bool,
) -> bool:
    """Gate one entry. Pure so every refusal reason is unit-testable.

    Opens only when there's a burst, we're under the per-symbol position cap,
    the post-trade cooldown has elapsed, and the day isn't halted (loss limit).
    """
    if direction is None:
        return False
    if daily_halted:
        return False
    if not cooldown_ok:
        return False
    if open_on_symbol >= max_per_symbol:
        return False
    return True


__all__ = ["detect_explosion", "should_open", "Direction"]
