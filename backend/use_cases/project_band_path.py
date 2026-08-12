"""Typical route ahead inside the Bollinger band, measured on past bars.

Pure functions over a list of `IntradayBar` — no I/O, easy to unit test.

THE QUESTION: "if price taps a band, does it come back?" A random walk cannot
answer that (it has no mean reversion), so we don't model it — we measure it.
Every past bar where price sat at the same spot inside its band (`pct_b`) is an
analog; we read what actually happened over the next `HORIZON_BARS` and report
the median route, the middle-half cone, and how often each band was touched.

MARKET STATE MATTERS. Coming back to the middle band from the upper one means
something very different in a climbing market with the bands opening up than it
does in a quiet range. So the return-to-mid figure is measured only on analogs
that were in the SAME state — trend of the middle band, bands expanding or
squeezing, and whether an outsized candle was driving one way. Conditioning
costs sample size, so the filter is relaxed in a fixed order (push → width →
trend) until the sample is usable, and the result says what it held constant.

Touches are judged on bar highs/lows — that is what a band touch means on a
chart — while the bands themselves are the standard close-based Bollinger.
"""

from __future__ import annotations

from statistics import median
from typing import Sequence

from core.enums import AssetSymbol
from core.models import (
    BandPathPoint,
    BandRegime,
    BandReturnToMid,
    BandRoundTrip,
    BandScenario,
    IntradayBar,
)

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

# --- market state ------------------------------------------------------------
# The thresholds below are CALIBRATED on ~5 days of live M5 bars across all six
# traded symbols, not guessed: each one sits at a percentile that actually
# splits the data, so all three buckets stay populated and conditioning does
# not starve the sample. Re-check them if the asset list changes a lot.
#
# Trend: how far the middle band travelled over the last bars, in band widths.
# Using the band's own width as the yardstick keeps it comparable across
# symbols and across quiet/wild sessions. 0.12 is the median |travel| on live
# data — half the bars are quieter than this, so "flat" means "the calmer half".
TREND_LOOKBACK = 5
TREND_FLAT = 0.12
# Width: today's band width against its own recent baseline. This is the
# "as bandas estão alargando?" test — a squeeze behaves nothing like a blow-out.
# Live ratios run from ~0.57 (p15) to ~1.71 (p85), so 0.80/1.25 cuts it into
# roughly even thirds. Tighter bounds (e.g. 0.85/1.15) would leave "steady"
# nearly empty and label almost every bar as one extreme or the other.
WIDTH_LOOKBACK = 50
WIDTH_EXPANDING = 1.25
WIDTH_SQUEEZING = 0.80
# Push: one outsized candle trying to break away. Measured against the normal
# candle size of the recent session, so it means the same thing on GOLD and on
# US30. 1.8x is the ~90th percentile live — big enough to be rare, common
# enough to gather a sample.
PUSH_LOOKBACK = 20
PUSH_BIG = 1.8

# Relaxation order for the state filter (each entry is what stays HELD): the
# least informative condition is dropped first, so the number keeps controlling
# for what matters most. Measured over ~5 days of live bars, starting from a
# band touch, the width of the bands is by far the strongest signal — 52% get
# back to the middle while the bands are squeezing against 28% while they are
# expanding — with the trend second (55% vs 37% off the lower band) and a
# single big candle the weakest. So width is the last thing let go.
_FILTERS: tuple[tuple[str, ...], ...] = (
    ("trend", "width", "push"),
    ("trend", "width"),
    ("width",),
    (),
)
_FILTER_LABELS = {"trend": "tendência", "width": "largura", "push": "candle grande"}

Bands = tuple[float, float, float]  # (upper, mid, lower)


def _all_bands(closes: Sequence[float]) -> list[Bands | None]:
    """Bollinger bands per bar, index-aligned (None before the first full window)."""
    out: list[Bands | None] = [None] * len(closes)
    for end in range(BAND_PERIOD - 1, len(closes)):
        window = closes[end - BAND_PERIOD + 1 : end + 1]
        mid = sum(window) / BAND_PERIOD
        sd = (sum((c - mid) ** 2 for c in window) / BAND_PERIOD) ** 0.5
        out[end] = (mid + BAND_MULT * sd, mid, mid - BAND_MULT * sd)
    return out


def _rolling_median(values: Sequence[float], index: int, lookback: int) -> float | None:
    """Median of `values` over the `lookback` bars ending at `index`."""
    if index + 1 < lookback:
        return None
    window = [v for v in values[index - lookback + 1 : index + 1] if v > 0]
    return median(window) if window else None


def _regime(
    index: int,
    bars: Sequence[IntradayBar],
    bands: Sequence[Bands | None],
    ranges: Sequence[float],
) -> BandRegime | None:
    """Read the market state at `index`, or None when there isn't history for it."""
    here = bands[index]
    if here is None:
        return None
    upper, mid, lower = here
    width = upper - lower
    if width <= 0:
        return None

    past = bands[index - TREND_LOOKBACK] if index >= TREND_LOOKBACK else None
    if past is None:
        return None
    travel = (mid - past[1]) / width
    trend = "flat" if abs(travel) < TREND_FLAT else ("up" if travel > 0 else "down")

    base_width = _rolling_median(
        [(b[0] - b[2]) if b else 0.0 for b in bands], index, WIDTH_LOOKBACK
    )
    if not base_width:
        return None
    ratio = width / base_width
    band_width = (
        "expanding"
        if ratio > WIDTH_EXPANDING
        else "squeezing" if ratio < WIDTH_SQUEEZING else "steady"
    )

    normal = _rolling_median(ranges, index, PUSH_LOOKBACK)
    bar = bars[index]
    if normal and ranges[index] > PUSH_BIG * normal and bar.close != bar.open:
        push = "up" if bar.close > bar.open else "down"
    else:
        push = "none"

    return BandRegime(trend=trend, width=band_width, push=push)  # type: ignore[arg-type]


def _same_state(a: BandRegime, b: BandRegime, keys: tuple[str, ...]) -> bool:
    return all(getattr(a, k) == getattr(b, k) for k in keys)


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


def _steps_to_mid(
    bars: Sequence[IntradayBar], start: int, horizon: int, mid: float, from_below: bool
) -> int | None:
    """Bars taken to reach the middle band, or None if it wasn't reached."""
    for step in range(1, horizon + 1):
        bar = bars[start + step]
        if bar.high >= mid if from_below else bar.low <= mid:
            return step
    return None


def _return_to_mid(
    analogs: list[int],
    now: BandRegime,
    states: dict[int, BandRegime],
    steps: dict[int, int | None],
    min_samples: int,
) -> BandReturnToMid | None:
    """Chance of getting back to the middle band, conditioned on today's state.

    Walks the relaxation order until a filter leaves enough analogs; returns
    None when even the unfiltered set is too thin.
    """
    for keys in _FILTERS:
        matched = [i for i in analogs if _same_state(states[i], now, keys)]
        if len(matched) < min_samples:
            continue
        reached = [s for s in (steps[i] for i in matched) if s is not None]
        return BandReturnToMid(
            pct=len(reached) / len(matched),
            regime_n=len(matched),
            matched_on=[_FILTER_LABELS[k] for k in keys],
            median_bars=round(median(reached)) if reached else None,
        )
    return None


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
    ranges = [b.high - b.low for b in bars]
    bands = _all_bands(closes)
    last = len(bars) - 1
    here = bands[last]
    if here is None:
        return None
    upper, mid, lower = here
    width = upper - lower
    if width <= 0:
        return None
    pct_b_now = (closes[last] - lower) / width
    below_mid = closes[last] < mid
    now_state = _regime(last, bars, bands, ranges)

    # Analogs: past bars at the same spot inside their own band, with a full
    # horizon of bars after them to observe.
    deltas: list[list[float]] = []  # per analog: normalised close moves, step 1..horizon
    analogs: list[int] = []
    states: dict[int, BandRegime] = {}
    mid_steps: dict[int, int | None] = {}
    touched_upper = touched_lower = back_to_mid = 0
    up_first = down_first = 0
    up_first_back = down_first_back = 0
    for i in range(BAND_PERIOD - 1, last - horizon + 1):
        band = bands[i]
        if band is None:
            continue
        a_upper, a_mid, a_lower = band
        a_width = a_upper - a_lower
        if a_width <= 0:
            continue
        if abs((closes[i] - a_lower) / a_width - pct_b_now) > tolerance:
            continue
        deltas.append([(closes[i + step] - closes[i]) / a_width for step in range(1, horizon + 1)])
        # Getting back to the middle band, from whichever side price started
        # on. Measured on wicks, like the band touches.
        steps = _steps_to_mid(bars, i, horizon, a_mid, below_mid)
        back_to_mid += steps is not None
        state = _regime(i, bars, bands, ranges) if now_state is not None else None
        if state is not None:
            analogs.append(i)
            states[i] = state
            mid_steps[i] = steps
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
        regime=now_state,
        return_to_mid=(
            _return_to_mid(analogs, now_state, states, mid_steps, min_samples)
            if now_state is not None
            else None
        ),
    )
