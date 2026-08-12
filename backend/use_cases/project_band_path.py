"""Typical route ahead inside the Bollinger band, measured on past bars.

Pure functions over a list of `IntradayBar` — no I/O, easy to unit test.

THE QUESTION: "if price taps the lower band, does it come back to the upper
one?" A random walk cannot answer that (it has no mean reversion), so we don't
model it — we measure it. Every past bar where price sat at the same spot
inside its band (`pct_b`) is an analog; we read what actually happened over
the next `HORIZON_BARS` and report the median route, the middle-half cone, and
how often each band was touched (and touched *back*).

Touches are judged on bar highs/lows — that is what a band touch means on a
chart — while the bands themselves are the standard close-based Bollinger.
"""

from __future__ import annotations

from statistics import median
from typing import Sequence

from core.enums import AssetSymbol
from core.models import BandPathPoint, BandRoundTrip, BandScenario, IntradayBar

# Standard Bollinger settings — the ones on the trader's own chart.
BAND_PERIOD = 20
BAND_MULT = 2.0
# How far ahead to look. 12 bars = 1 hour on M5: long enough for a round trip,
# short enough that "what happened next" is still about this move.
HORIZON_BARS = 12
# How close a past bar must sit to today's spot in the band to count as an
# analog. 0.12 of the band width — tight enough to mean the same thing, loose
# enough to gather a sample within a couple of sessions.
PCT_B_TOLERANCE = 0.12
# Below this many analogs the numbers are noise and we report nothing.
MIN_SAMPLES = 12


def _bands(closes: Sequence[float], end: int) -> tuple[float, float, float]:
    """(upper, mid, lower) of the close-based Bollinger band ending at `end`."""
    window = closes[end - BAND_PERIOD + 1 : end + 1]
    mid = sum(window) / len(window)
    var = sum((c - mid) ** 2 for c in window) / len(window)
    sd = var**0.5
    return mid + BAND_MULT * sd, mid, mid - BAND_MULT * sd


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile of a NON-empty list (q in 0..1)."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = q * (len(ordered) - 1)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _first_touch(
    bars: Sequence[IntradayBar], start: int, horizon: int, upper: float, lower: float
) -> tuple[int | None, int | None]:
    """Step (1-based) at which each band is first touched after bar `start`.

    A bar touches the upper band when its HIGH reaches it, the lower band when
    its LOW reaches it. A bar can touch both — then the one it opened away from
    is unknowable from OHLC alone, so both are recorded at that step and the
    caller's `<` comparison treats them as "no clear first".
    """
    up_at: int | None = None
    down_at: int | None = None
    for step in range(1, horizon + 1):
        bar = bars[start + step]
        if up_at is None and bar.high >= upper:
            up_at = step
        if down_at is None and bar.low <= lower:
            down_at = step
        if up_at is not None and down_at is not None:
            break
    return up_at, down_at


def project_band_path(
    symbol: AssetSymbol,
    bars: Sequence[IntradayBar],
    *,
    horizon: int = HORIZON_BARS,
    tolerance: float = PCT_B_TOLERANCE,
    min_samples: int = MIN_SAMPLES,
) -> BandScenario | None:
    """Measure where price went from this spot in the band, on this symbol.

    Returns None when there aren't enough bars, the band has no width (a
    dead-flat window), or fewer than `min_samples` analogs were found — a thin
    sample must show nothing rather than a number nobody should trade.
    """
    if len(bars) < BAND_PERIOD + horizon + 1:
        return None
    closes = [b.close for b in bars]
    last = len(bars) - 1
    upper, mid, lower = _bands(closes, last)
    width = upper - lower
    if width <= 0:
        return None
    pct_b_now = (closes[last] - lower) / width

    # Analogs: past bars at the same spot inside their own band, with a full
    # horizon of bars after them to observe.
    deltas: list[list[float]] = []  # per analog: normalised close moves, step 1..horizon
    touched_upper = touched_lower = back_to_mid = 0
    up_first = down_first = 0
    up_first_back = down_first_back = 0
    below_mid = closes[last] < mid
    for i in range(BAND_PERIOD - 1, last - horizon + 1):
        a_upper, a_mid, a_lower = _bands(closes, i)
        a_width = a_upper - a_lower
        if a_width <= 0:
            continue
        if abs((closes[i] - a_lower) / a_width - pct_b_now) > tolerance:
            continue
        deltas.append([(closes[i + step] - closes[i]) / a_width for step in range(1, horizon + 1)])
        # Getting back to the middle band: reaching it from whichever side
        # price started on. Measured on wicks, like the band touches.
        future = bars[i + 1 : i + horizon + 1]
        back_to_mid += any((b.high >= a_mid if below_mid else b.low <= a_mid) for b in future)
        up_at, down_at = _first_touch(bars, i, horizon, a_upper, a_lower)
        touched_upper += up_at is not None
        touched_lower += down_at is not None
        if up_at is not None and (down_at is None or up_at < down_at):
            up_first += 1
            # Came back: the opposite band was touched later in the window.
            up_first_back += down_at is not None and down_at > up_at
        elif down_at is not None and (up_at is None or down_at < up_at):
            down_first += 1
            down_first_back += up_at is not None and up_at > down_at

    n = len(deltas)
    if n < min_samples:
        return None

    path = [
        BandPathPoint(
            step=step + 1,
            median=closes[last] + median(d[step] for d in deltas) * width,
            p25=closes[last] + _percentile([d[step] for d in deltas], 0.25) * width,
            p75=closes[last] + _percentile([d[step] for d in deltas], 0.75) * width,
        )
        for step in range(horizon)
    ]
    return BandScenario(
        symbol=symbol,
        asof=bars[last].timestamp,
        last_close=closes[last],
        upper=upper,
        mid=mid,
        lower=lower,
        pct_b=pct_b_now,
        samples=n,
        horizon_bars=horizon,
        path=path,
        touch_upper_pct=touched_upper / n,
        touch_lower_pct=touched_lower / n,
        back_to_mid_pct=back_to_mid / n,
        upper_first=(
            BandRoundTrip(n=up_first, back_pct=up_first_back / up_first) if up_first else None
        ),
        lower_first=(
            BandRoundTrip(n=down_first, back_pct=down_first_back / down_first)
            if down_first
            else None
        ),
    )
