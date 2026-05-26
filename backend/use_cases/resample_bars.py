"""Bar resampling: group base 5-min bars into higher-timeframe OHLCV bars.

Pure function. The grouping is by **bar count** (not wall-clock time) so the
output is deterministic and works for both RTH-only equities (^NDX, ^GSPC)
and near-24h futures (GC=F). The wrinkle: this means "4h" really means
"48 5m bars of trading time", not "from 09:00 to 13:00 ET" — for breakout
detection what we care about is the trading-time structure, not the clock.

We deliberately drop the *partial* trailing group so we never emit a signal
on a bar that has not closed yet.
"""

from __future__ import annotations

from typing import Sequence

from core.enums import Timeframe
from core.models import IntradayBar

# 5-min bars per higher-timeframe bar.
BARS_PER_TIMEFRAME: dict[Timeframe, int] = {
    Timeframe.M5: 1,
    Timeframe.M15: 3,
    Timeframe.M30: 6,
    Timeframe.H1: 12,
    Timeframe.H4: 48,
}


def resample_to(base_bars: Sequence[IntradayBar], target: Timeframe) -> list[IntradayBar]:
    """Aggregate 5-min `base_bars` into `target` timeframe bars.

    Drops any partial trailing group (e.g. only 2 of 3 bars present for M15
    → last group is skipped). The OHLCV semantics: open=first.open,
    high=max(highs), low=min(lows), close=last.close, volume=sum(volumes).
    Timestamp inherits from the first bar in the group.
    """
    n = BARS_PER_TIMEFRAME[target]
    if n <= 1:
        return list(base_bars)

    out: list[IntradayBar] = []
    # Only iterate over complete groups — `len(base_bars) // n` is how many
    # full groups we have.
    full_groups = len(base_bars) // n
    for i in range(full_groups):
        group = base_bars[i * n : (i + 1) * n]
        first = group[0]
        last = group[-1]
        out.append(
            IntradayBar(
                timestamp=first.timestamp,
                open=first.open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=last.close,
                volume=sum(b.volume for b in group),
            )
        )
    return out
