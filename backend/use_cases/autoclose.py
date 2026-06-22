"""Pure decision logic for the profit-target auto-close.

Kept tiny and side-effect-free so the rule that triggers *real order execution*
is exhaustively unit-testable. The backend is the brain (this function); the
collector is the hand (it receives the resulting `close_all` command and is the
only place that talks to MT5). The collector also has its own `allow_auto_close`
gate, so execution needs BOTH the backend to fire and the collector to permit.
"""

from __future__ import annotations


def should_autoclose(open_profit: float, target_usd: float | None, armed: bool) -> bool:
    """True when the armed whole-account profit target is reached.

    `target_usd` must be a positive number — a missing or non-positive target
    never fires (guards against arming at break-even or with a fat-fingered 0).
    """
    if not armed or target_usd is None or target_usd <= 0:
        return False
    return open_profit >= target_usd


__all__ = ["should_autoclose"]
