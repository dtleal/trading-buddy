"""Deterministic intraday level computation for `dtb signal`.

Pure function over a list of IntradayBar — no I/O, easy to unit test.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Sequence

from core.models import IntradayBar, IntradayLevels

# US regular session, 09:30 ET = 13:30 UTC (EDT) / 14:30 UTC (EST).
# We accept both windows; the first bar at or after 13:30 UTC anchors RTH.
US_SESSION_START_UTC_EDT = time(13, 30)
US_SESSION_START_UTC_EST = time(14, 30)
DEFAULT_OPENING_RANGE_MINUTES = 30


def _is_rth_open_utc(ts: datetime) -> bool:
    """Heuristic: bar belongs to the regular US session if its UTC time of day
    falls at or after the EDT open (13:30) — covers both EDT and EST openings.
    """
    return ts.timetz().replace(tzinfo=timezone.utc) >= US_SESSION_START_UTC_EDT.replace(
        tzinfo=timezone.utc
    )


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1.0 - k)
    return ema


def _sma(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _atr(bars: Sequence[IntradayBar], period: int) -> float | None:
    if len(bars) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(bars)):
        h, lo = bars[i].high, bars[i].low
        prev_close = bars[i - 1].close
        tr = max(h - lo, abs(h - prev_close), abs(lo - prev_close))
        trs.append(tr)
    # Wilder's smoothing
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def _vwap(bars: Sequence[IntradayBar]) -> float | None:
    total_pv = 0.0
    total_v = 0.0
    for b in bars:
        typical = (b.high + b.low + b.close) / 3.0
        total_pv += typical * b.volume
        total_v += b.volume
    if total_v <= 0:
        return None
    return total_pv / total_v


def _opening_range(
    session_bars: Sequence[IntradayBar],
    minutes: int,
) -> tuple[float | None, float | None]:
    if not session_bars:
        return None, None
    open_ts = session_bars[0].timestamp
    cutoff = open_ts + timedelta(minutes=minutes)
    window = [b for b in session_bars if b.timestamp < cutoff]
    if not window:
        return None, None
    return max(b.high for b in window), min(b.low for b in window)


def _last_swings(
    bars: Sequence[IntradayBar],
    left: int = 2,
    right: int = 2,
) -> tuple[float | None, datetime | None, float | None, datetime | None]:
    """3-bar fractal style pivots (default left=right=2 → 5-bar pivot).

    A bar at index i is a swing high if its high is strictly greater than all
    `left` previous and all `right` following highs. Symmetric for swing low.
    Returns the most recent swing high/low (or None if none yet).
    """
    if len(bars) < left + right + 1:
        return None, None, None, None
    last_sh: tuple[float, datetime] | None = None
    last_sl: tuple[float, datetime] | None = None
    for i in range(left, len(bars) - right):
        window_l = bars[i - left : i]
        window_r = bars[i + 1 : i + 1 + right]
        center = bars[i]
        if all(center.high > b.high for b in window_l) and all(
            center.high > b.high for b in window_r
        ):
            last_sh = (center.high, center.timestamp)
        if all(center.low < b.low for b in window_l) and all(center.low < b.low for b in window_r):
            last_sl = (center.low, center.timestamp)
    return (
        last_sh[0] if last_sh else None,
        last_sh[1] if last_sh else None,
        last_sl[0] if last_sl else None,
        last_sl[1] if last_sl else None,
    )


def _split_sessions(
    bars: Sequence[IntradayBar],
) -> tuple[list[IntradayBar], list[IntradayBar]]:
    """Split bars into (today's session, previous day's session) by UTC date.

    Uses the date of the *latest* bar as "today" and the date immediately
    before that as "previous day". Bars from other dates are dropped.
    """
    if not bars:
        return [], []
    today_date = bars[-1].timestamp.date()
    prev_date = today_date - timedelta(days=1)
    today = [b for b in bars if b.timestamp.date() == today_date]
    prev = [b for b in bars if b.timestamp.date() == prev_date]
    return today, prev


class ComputeIntradayLevelsUseCase:
    """Pure computation. Inject nothing; call `execute(symbol, bars)`."""

    def __init__(self, opening_range_minutes: int = DEFAULT_OPENING_RANGE_MINUTES) -> None:
        self._or_minutes = opening_range_minutes

    def execute(self, symbol: str, bars: Sequence[IntradayBar]) -> IntradayLevels | None:
        if not bars:
            return None

        today, prev = _split_sessions(bars)
        if not today:
            return None

        # Previous-day OHLC (full session, not just RTH — keeps it simple)
        pdc = prev[-1].close if prev else None
        pdh = max(b.high for b in prev) if prev else None
        pdl = min(b.low for b in prev) if prev else None

        # Today's RTH window (best-effort by UTC time-of-day)
        rth = [b for b in today if _is_rth_open_utc(b.timestamp)] or today

        hod = max(b.high for b in rth)
        lod = min(b.low for b in rth)
        vwap = _vwap(rth)
        orh, orl = _opening_range(rth, self._or_minutes)

        closes_today = [b.close for b in today]
        ema_9 = _ema(closes_today, 9)
        ema_20 = _ema(closes_today, 20)
        ema_50 = _ema(closes_today, 50)
        atr_14 = _atr(today, 14)

        # Long-period MAs need bars from earlier sessions (200×5m ≈ 17h trading).
        closes_all = [b.close for b in bars]
        ema_200 = _ema(closes_all, 200)
        sma_200 = _sma(closes_all, 200)

        sh, sh_at, sl, sl_at = _last_swings(rth)

        last = today[-1]
        return IntradayLevels(
            symbol=symbol,
            asof=last.timestamp,
            last_price=last.close,
            hod=hod,
            lod=lod,
            vwap=vwap,
            orh=orh,
            orl=orl,
            pdc=pdc,
            pdh=pdh,
            pdl=pdl,
            ema_9=ema_9,
            ema_20=ema_20,
            ema_50=ema_50,
            ema_200=ema_200,
            sma_200=sma_200,
            atr_14=atr_14,
            last_swing_high=sh,
            last_swing_high_at=sh_at,
            last_swing_low=sl,
            last_swing_low_at=sl_at,
        )
