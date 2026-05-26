"""Breakout detector — Donchian channel + volatility expansion + squeeze filter.

Pure function. Given a series of bars (already on the target timeframe), scans
the recent N bars for *fresh* Donchian breakouts and returns one Breakout per
signal-bar that satisfied all four conditions:

  1. Donchian break: bar.close > max(high of the N previous bars), or symmetric down.
  2. Fresh cross:    the *previous* bar's close was inside the channel — this
                     filters continuation noise where price has been above the
                     level for many bars already.
  3. Range expansion: bar_range (high - low) > expansion_atr_multiple × ATR(14).
  4. Squeeze (quality, optional): ATR(14) on the signal bar was below the
     20-bar SMA of ATR — i.e. volatility was contracting *before* the break.

The `squeeze` filter is recommended but tunable: it makes the detector less
sensitive on already-volatile days. Set `require_squeeze=False` to fire on any
Donchian break that meets conditions 1-3.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from core.enums import AssetSymbol, BreakoutDirection, Timeframe
from core.models import Breakout, IntradayBar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BreakoutThresholds:
    """Tunable parameters. Defaults are the user-confirmed conservative profile."""

    donchian_n: int = 20
    expansion_atr_multiple: float = 1.3
    require_squeeze: bool = True
    atr_window: int = 14
    atr_sma_window: int = 20  # used by squeeze filter


# How many recent bars we scan for fresh breakouts in a single call. Each tick
# we re-evaluate this window; older signals fall off and the frontend dedups
# by id.
SCAN_WINDOW = 50


class DetectBreakoutsUseCase:
    """Pure detector. `execute(asset, tf, bars)` → list of Breakout signals."""

    def __init__(self, thresholds: BreakoutThresholds | None = None) -> None:
        self._t = thresholds or BreakoutThresholds()

    def execute(
        self,
        asset: AssetSymbol,
        timeframe: Timeframe,
        bars: Sequence[IntradayBar],
    ) -> list[Breakout]:
        n = self._t.donchian_n
        # We need at least N+1 bars to evaluate a single signal (N for the
        # channel, 1 for the candidate), and a few more for ATR / ATR-SMA.
        min_required = max(
            n + 1, self._t.atr_window + 1, self._t.atr_sma_window + self._t.atr_window
        )
        if len(bars) < min_required:
            return []

        atr_series = _rolling_atr(bars, self._t.atr_window)
        atr_sma = _sma(atr_series, self._t.atr_sma_window)

        # Scan the most recent SCAN_WINDOW bars (skipping bars too early to
        # have a Donchian window behind them).
        scan_start = max(n, len(bars) - SCAN_WINDOW)
        signals: list[Breakout] = []
        now = datetime.now(timezone.utc)

        for i in range(scan_start, len(bars)):
            # Use ATR from the bar *before* the candidate. Using `atr_series[i]`
            # would include the candidate's own (huge) range in the denominator,
            # making expansion appear small and the squeeze condition trivially
            # fail every legitimate breakout.
            ref_idx = i - 1
            atr = atr_series[ref_idx] if ref_idx >= 0 else None
            if atr is None or atr <= 0:
                continue

            signal = _try_signal(
                asset=asset,
                timeframe=timeframe,
                bars=bars,
                i=i,
                atr=atr,
                atr_sma=atr_sma[ref_idx] if ref_idx < len(atr_sma) else None,
                thresholds=self._t,
                now=now,
            )
            if signal is not None:
                signals.append(signal)
        return signals


# ---------- helpers ----------


def _try_signal(
    *,
    asset: AssetSymbol,
    timeframe: Timeframe,
    bars: Sequence[IntradayBar],
    i: int,
    atr: float,
    atr_sma: float | None,
    thresholds: BreakoutThresholds,
    now: datetime,
) -> Breakout | None:
    candidate = bars[i]
    prev = bars[i - 1]
    window = bars[i - thresholds.donchian_n : i]
    don_high = max(b.high for b in window)
    don_low = min(b.low for b in window)
    bar_range = candidate.high - candidate.low
    expansion = bar_range / atr if atr > 0 else 0.0

    if expansion < thresholds.expansion_atr_multiple:
        return None

    squeeze_ok = True
    if thresholds.require_squeeze:
        # Strictly greater means volatility was already expanding before this
        # bar. Flat ATR (`atr == atr_sma`) still counts as "in squeeze".
        if atr_sma is None or atr > atr_sma:
            squeeze_ok = False
    if not squeeze_ok:
        return None

    # UP breakout
    if candidate.close > don_high and prev.close <= don_high:
        return _build_breakout(
            asset=asset,
            timeframe=timeframe,
            direction=BreakoutDirection.UP,
            level=don_high,
            candidate=candidate,
            bar_range=bar_range,
            expansion=expansion,
            squeeze=thresholds.require_squeeze,
            now=now,
        )
    # DOWN breakout (mirror)
    if candidate.close < don_low and prev.close >= don_low:
        return _build_breakout(
            asset=asset,
            timeframe=timeframe,
            direction=BreakoutDirection.DOWN,
            level=don_low,
            candidate=candidate,
            bar_range=bar_range,
            expansion=expansion,
            squeeze=thresholds.require_squeeze,
            now=now,
        )
    return None


def _build_breakout(
    *,
    asset: AssetSymbol,
    timeframe: Timeframe,
    direction: BreakoutDirection,
    level: float,
    candidate: IntradayBar,
    bar_range: float,
    expansion: float,
    squeeze: bool,
    now: datetime,
) -> Breakout:
    # Distance past the level, normalized by bar range — combined with
    # expansion to form a 0-100 strength score.
    distance_norm = abs(candidate.close - level) / bar_range if bar_range > 0 else 0.0
    strength = min(100.0, 50.0 * expansion + 30.0 * distance_norm)

    bar_id_seed = (
        f"{asset.value}|{timeframe.value}|{direction.value}|{candidate.timestamp.isoformat()}"
    )
    breakout_id = hashlib.sha1(bar_id_seed.encode("utf-8")).hexdigest()[:16]

    return Breakout(
        id=breakout_id,
        asset=asset,
        timeframe=timeframe,
        direction=direction,
        level=level,
        close=candidate.close,
        bar_range=bar_range,
        expansion_ratio=expansion,
        strength=strength,
        squeeze=squeeze,
        signal_bar_at=candidate.timestamp,
        detected_at=now,
    )


def _rolling_atr(bars: Sequence[IntradayBar], window: int) -> list[float | None]:
    """Wilder's ATR. `result[i]` is the ATR at bar `i` (None until window is filled)."""
    n = len(bars)
    if n < window + 1:
        return [None] * n

    trs: list[float] = []
    for i in range(1, n):
        h = bars[i].high
        lo = bars[i].low
        prev_close = bars[i - 1].close
        trs.append(max(h - lo, abs(h - prev_close), abs(lo - prev_close)))

    # trs[i] corresponds to bars[i+1]. ATR at bars[i] is None until i >= window.
    result: list[float | None] = [None] * n
    # First ATR = simple average of first `window` TRs → aligns with bars[window]
    atr = sum(trs[:window]) / window
    result[window] = atr
    for j in range(window, len(trs)):
        atr = (atr * (window - 1) + trs[j]) / window
        # trs[j] corresponds to bars[j + 1]
        result[j + 1] = atr
    return result


def _sma(values: Sequence[float | None], window: int) -> list[float | None]:
    """Simple moving average over a series with possible None gaps."""
    n = len(values)
    out: list[float | None] = [None] * n
    for i in range(n):
        chunk = values[max(0, i - window + 1) : i + 1]
        nonnull = [v for v in chunk if v is not None]
        if len(nonnull) == window:
            out[i] = sum(nonnull) / window
    return out
