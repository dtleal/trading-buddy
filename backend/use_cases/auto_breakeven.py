"""Pure decision logic for the per-position auto-breakeven.

Same split as the account auto-close (`autoclose.py`): the backend is the brain
(these functions), the collector is the hand — it receives the resulting
`breakeven_tickets` command and is the only place that talks to MT5. The
collector's own `allow_auto_close` gate still applies, so execution needs BOTH
sides to agree.

THE RULE: the moment one position's floating profit reaches the threshold, its
stop-loss is moved to its entry price, so that trade can no longer come back and
lose money. It is per POSITION, not per account: a winner is protected while
another position is still working.

A position already protected is left alone — both because re-sending is noise
and because its stop may have been trailed past entry by hand, and moving it
back to entry would LOOSEN it.
"""

from __future__ import annotations

from typing import Iterable

from core.models import Position


def at_breakeven_or_better(position: Position) -> bool:
    """True when the stop-loss already sits at entry or beyond it.

    MT5 reports "no stop" as 0.0 (the collector passes it through as 0.0 or
    None), which is why the zero check comes first: 0.0 is not a stop below
    entry on a long, it is the absence of one.
    """
    sl = position.sl
    if not sl:  # None or 0.0 → no stop set
        return False
    if position.side == "buy":
        return sl >= position.price_open
    return sl <= position.price_open


def in_profit(position: Position) -> bool:
    """True when price has moved in the trade's favour.

    A stop at entry is only a valid order once it sits on the protective side of
    the market; sending it while the trade is still underwater is rejected by
    the broker, so those positions are not asked for.
    """
    if position.side == "buy":
        return position.price_current > position.price_open
    return position.price_current < position.price_open


def tickets_to_protect(
    positions: Iterable[Position], threshold_usd: float | None, armed: bool
) -> list[int]:
    """Tickets whose stop-loss should be moved to entry right now.

    `threshold_usd` must be positive — a missing or non-positive threshold never
    fires (arming at 0 would try to protect every position the instant it opens,
    while it is still inside the spread).
    """
    if not armed or threshold_usd is None or threshold_usd <= 0:
        return []
    return [
        p.ticket
        for p in positions
        if p.profit >= threshold_usd and in_profit(p) and not at_breakeven_or_better(p)
    ]


def protected_count(positions: Iterable[Position]) -> int:
    """How many open positions already have their stop at entry or better —
    what the UI shows as "N protegida(s)"."""
    return sum(1 for p in positions if at_breakeven_or_better(p))


__all__ = [
    "at_breakeven_or_better",
    "in_profit",
    "protected_count",
    "tickets_to_protect",
]
