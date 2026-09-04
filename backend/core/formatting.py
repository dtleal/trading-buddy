"""Price formatting shared by the CLI and the LLM payload."""

from __future__ import annotations


def price_digits(price: float) -> int:
    """How many decimals a price needs to still say something.

    The indices read fine with two (30,075.68), but EURUSD trades at 1.15957 —
    two decimals there would hide a whole day of movement. Anything priced
    under 10 therefore gets five.

    Pass the *asset price* even when formatting something derived from it (a
    stop distance, a range, an ATR): a 3.2-point gap on the Nasdaq should still
    print as 3.20, not 3.20000.
    """
    return 5 if abs(price) < 10 else 2


def fmt_price(value: float, *, digits: int | None = None, grouped: bool = False) -> str:
    """Format a price. `grouped` adds thousands separators (30,075.68)."""
    d = price_digits(value) if digits is None else digits
    return f"{value:,.{d}f}" if grouped else f"{value:.{d}f}"
