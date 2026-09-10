"""Support/resistance zones from repeated touches that held.

Pure functions over lists of `IntradayBar` — no I/O, easy to unit test.

THE READ THIS AUTOMATES: on the chart you spot a price the market turned at
three or more times without closing through it, and you treat it as a region,
not a line. The same region showing up on the daily, the 15m and the 5m is the
one that matters. That is exactly what this computes:

1. **Pivots.** A swing high is a bar whose high beats `_PIVOT_WING` bars on
   each side; a swing low is the mirror. Highs and lows are kept apart — a
   level held from below (highs) is a different fact from one held from above
   (lows), and a level that did both is the strongest kind there is.
2. **Clusters.** Pivots closer together than `_TOL_ATR` × ATR of that
   timeframe are the same level. The cluster's edges (its lowest and highest
   pivot) ARE the zone — that is where the width comes from, not a fixed
   padding.
3. **"Never closed through."** Between the first and the last touch, a bar
   closing beyond the level on the side the touches came from means the level
   broke. One such close is noise; more than `_MAX_PIERCES` and the cluster is
   dropped.
4. **Confluence.** Zones from different timeframes that overlap are merged into
   one, and the score adds up, so a daily zone confirmed at 15m and 5m outranks
   anything found on a single timeframe.

Scoring is deliberately simple — touches weighted by timeframe. The daily
weighs most because its touches are days apart, while three 5m touches can all
belong to the same hour.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from core.enums import AssetSymbol, Timeframe
from core.models import IntradayBar, PriceZone, ZoneKind
from use_cases.resample_bars import resample_to

# A pivot must beat this many bars on each side. 2 is what the eye picks up as
# a swing on a candle chart; 3+ only finds the majors and misses intraday
# levels that get respected all day.
_PIVOT_WING = 2

# Two pivots are the same level when they sit within this fraction of the
# timeframe's ATR. 0.25 is what makes a zone read as a REGION rather than a
# line — tighter than this and one obvious shelf splits into three hairlines
# on the chart; wider and two genuinely separate levels get smeared into one.
_TOL_ATR = 0.25

# Bars used for the ATR that sizes the tolerance.
_ATR_BARS = 14

# Touches needed on a single timeframe before a level counts at all — the "at
# least 3 times" rule.
_MIN_TOUCHES = 3

# Closes allowed through the level between its first and last touch. One is
# noise (a wick-heavy bar closing a hair past); two means it broke.
_MAX_PIERCES = 1

# How far a close must be past the zone edge to count as a pierce, as a
# fraction of ATR. Without it, a close a cent past the edge would kill a good
# level.
_PIERCE_ATR = 0.25

# How much history each timeframe looks back over. The point of the cutoff is
# that a level nobody has traded against in weeks is not a level any more; it
# also keeps the pivot scan cheap.
_LOOKBACK_BARS: dict[Timeframe, int] = {
    Timeframe.M5: 576,  # ~2 sessions of 24h bars
    Timeframe.M15: 480,  # ~5 days
}
_D1_LOOKBACK_BARS = 180  # ~9 months of sessions

# Touches counted TOWARDS THE SCORE per cluster. The 20th tap of a level says
# nothing the 6th did not, and without a cap a busy 5m level outscores a
# daily one just by having more bars. The reported `touches` is the real count.
_MAX_SCORED_TOUCHES = 6

# Score weight per timeframe. A daily touch is worth three 5m touches: its
# touches are days apart, so they are independent events.
_TF_WEIGHT: dict[str, float] = {"1d": 3.0, "15m": 1.5, "5m": 1.0}

# Score that reads as a full-strength zone (used only to normalise `strength`
# for the drawing). Three daily touches alone (9.0) is already very strong.
_FULL_SCORE = 12.0

# M5 bars in a trading day, used as the yardstick for how far away a zone can
# still matter (see `_MAX_REACH_DAYS`). 24h of 5-minute bars.
_BARS_PER_DAY = 288

# How far from the price a zone may sit, in days of trading range. 1.5 keeps
# everything price could plausibly reach in a session or two and drops the
# levels from months ago that sit 10% away.
_MAX_REACH_DAYS = 1.5

# Zones returned per symbol on each side of price. More than this is noise on
# a chart and the trader stops reading any of them.
_MAX_PER_SIDE = 4

_DAILY = "1d"


def _atr(bars: Sequence[IntradayBar]) -> float:
    """Mean bar range over the last `_ATR_BARS` bars. Simple range, not the
    Wilder ATR — it only has to size a tolerance."""
    window = bars[-_ATR_BARS:]
    if not window:
        return 0.0
    return sum(b.high - b.low for b in window) / len(window)


def _pivots(bars: Sequence[IntradayBar], *, high: bool) -> list[tuple[float, datetime]]:
    """Swing highs (or lows) as (price, timestamp), oldest first.

    The bar must beat `_PIVOT_WING` neighbours on BOTH sides, so the newest and
    oldest few bars can never be pivots — a swing is not confirmed until price
    has moved away from it.
    """
    out: list[tuple[float, datetime]] = []
    for i in range(_PIVOT_WING, len(bars) - _PIVOT_WING):
        bar = bars[i]
        window = bars[i - _PIVOT_WING : i + _PIVOT_WING + 1]
        price = bar.high if high else bar.low
        if high and price >= max(b.high for b in window):
            out.append((price, bar.timestamp))
        elif not high and price <= min(b.low for b in window):
            out.append((price, bar.timestamp))
    return out


class _Cluster:
    """Pivots of one kind, on one timeframe, that share a price level."""

    def __init__(self, timeframe: str, high: bool) -> None:
        self.timeframe = timeframe
        self.high = high
        self.prices: list[float] = []
        self.times: list[datetime] = []

    def add(self, price: float, at: datetime) -> None:
        self.prices.append(price)
        self.times.append(at)

    @property
    def low(self) -> float:
        return min(self.prices)

    @property
    def top(self) -> float:
        return max(self.prices)

    @property
    def touches(self) -> int:
        return len(self.prices)


def _cluster(
    pivots: Sequence[tuple[float, datetime]], tol: float, timeframe: str, high: bool
) -> list[_Cluster]:
    """Group pivots into levels: walk them in price order and start a new
    cluster as soon as the price is more than `tol` above the cluster's LOWEST
    pivot.

    Measuring from the cluster's own bottom (not from the previous pivot) is
    what keeps a zone a zone: with a dense pivot field, each pivot sits within
    `tol` of the one before it, so chaining pivot-to-pivot would swallow the
    whole chart into a single band. This caps every cluster at `tol` wide.
    """
    clusters: list[_Cluster] = []
    current: _Cluster | None = None
    for price, at in sorted(pivots):
        if current is None or price - current.low > tol:
            current = _Cluster(timeframe, high)
            clusters.append(current)
        current.add(price, at)
    return clusters


def _pierced(bars: Sequence[IntradayBar], cluster: _Cluster, margin: float) -> int:
    """How many bars closed through the level while it was being tested.

    Only the span between the first and last touch counts: what happened
    before the level existed is irrelevant, and what happened after is the
    level being taken out later, which the recency cutoff already handles.
    """
    first, last = min(cluster.times), max(cluster.times)
    count = 0
    for bar in bars:
        if bar.timestamp < first or bar.timestamp > last:
            continue
        if cluster.high and bar.close > cluster.top + margin:
            count += 1
        elif not cluster.high and bar.close < cluster.low - margin:
            count += 1
    return count


def _clusters_for(bars: Sequence[IntradayBar], timeframe: str) -> list[_Cluster]:
    """Every level on one timeframe that was touched enough and never broke."""
    atr = _atr(bars)
    if atr <= 0:
        return []
    tol = _TOL_ATR * atr
    margin = _PIERCE_ATR * atr
    kept: list[_Cluster] = []
    for high in (True, False):
        for cluster in _cluster(_pivots(bars, high=high), tol, timeframe, high):
            if cluster.touches < _MIN_TOUCHES:
                continue
            if _pierced(bars, cluster, margin) > _MAX_PIERCES:
                continue
            kept.append(cluster)
    return kept


class _Zone:
    """One or more clusters (across timeframes) sharing a price band."""

    def __init__(self, cluster: _Cluster) -> None:
        self.low = cluster.low
        self.high = cluster.top
        self.clusters = [cluster]

    @property
    def width(self) -> float:
        return self.high - self.low

    def overlaps(self, cluster: _Cluster, tol: float) -> bool:
        """Touching (within `tol`) AND the merge barely widens the band.

        The width check is what stops a chain of neighbouring levels growing
        into one useless band across half the chart: the merged band may not
        end up more than `tol` wider than the widest side going in. Comparing
        against the participants (not a fixed cap) is what lets a broad daily
        shelf absorb the 5m levels inside it while two separate intraday
        levels a few points apart stay separate.
        """
        if cluster.low > self.high + tol or cluster.top < self.low - tol:
            return False
        merged = max(self.high, cluster.top) - min(self.low, cluster.low)
        return merged <= max(self.width, cluster.top - cluster.low) + tol

    def merge(self, cluster: _Cluster) -> None:
        self.low = min(self.low, cluster.low)
        self.high = max(self.high, cluster.top)
        self.clusters.append(cluster)

    @property
    def timeframes(self) -> list[str]:
        """Timeframes that touched this zone, strongest first."""
        seen = {c.timeframe for c in self.clusters}
        return [tf for tf in _TF_WEIGHT if tf in seen]

    @property
    def touches(self) -> int:
        return sum(c.touches for c in self.clusters)

    @property
    def last_touch(self) -> datetime:
        return max(max(c.times) for c in self.clusters)

    @property
    def kind(self) -> ZoneKind:
        highs = any(c.high for c in self.clusters)
        lows = any(not c.high for c in self.clusters)
        if highs and lows:
            return "both"
        return "top" if highs else "bottom"

    @property
    def score(self) -> float:
        # Touches weighted by timeframe. Same-timeframe touches add up (three
        # taps beat two); a level held from both sides gets a 1.5x bonus,
        # since price turned there going up AND coming down.
        base = sum(
            _TF_WEIGHT[c.timeframe] * min(c.touches, _MAX_SCORED_TOUCHES) for c in self.clusters
        )
        return round(base * (1.5 if self.kind == "both" else 1.0), 2)


def _merge_zones(clusters: Sequence[_Cluster], tol: float) -> list[_Zone]:
    """Fold overlapping clusters from every timeframe into single zones.

    Widest-first (daily clusters are widest) so a broad daily shelf absorbs the
    5m levels inside it instead of the other way round. `_Zone.overlaps` caps
    how wide the result may get, so confluence can only confirm a level, never
    smear several of them into one band.
    """
    zones: list[_Zone] = []
    for cluster in sorted(clusters, key=lambda c: c.top - c.low, reverse=True):
        for zone in zones:
            if zone.overlaps(cluster, tol):
                zone.merge(cluster)
                break
        else:
            zones.append(_Zone(cluster))
    return zones


class FindPriceZonesUseCase:
    """Price zones for one symbol from its stored M5 bars + daily bars.

    M15 is resampled from the M5 bars (`resample_bars`), so the only extra feed
    needed is the daily one. Symbols without enough bars simply get no zones —
    a level found on 40 candles is not a level.
    """

    def execute(
        self,
        symbol: AssetSymbol,
        m5_bars: Sequence[IntradayBar],
        d1_bars: Sequence[IntradayBar] = (),
    ) -> list[PriceZone]:
        clusters: list[_Cluster] = []
        m5 = list(m5_bars)[-_LOOKBACK_BARS[Timeframe.M5] :]
        if len(m5) > _ATR_BARS:
            clusters += _clusters_for(m5, "5m")
        m15 = resample_to(list(m5_bars), Timeframe.M15)[-_LOOKBACK_BARS[Timeframe.M15] :]
        if len(m15) > _ATR_BARS:
            clusters += _clusters_for(m15, "15m")
        d1 = list(d1_bars)[-_D1_LOOKBACK_BARS:]
        if len(d1) > _ATR_BARS:
            clusters += _clusters_for(d1, _DAILY)
        if not clusters or not m5:
            return []

        # Merge slack is sized on the M5 bars — the SMALLEST scale in play — on
        # purpose. Sizing it on the daily ATR (which is tens of times bigger)
        # let neighbouring intraday levels chain into one band hundreds of
        # points wide. A wide daily shelf still absorbs the intraday levels
        # inside it, because that is an overlap, not a gap.
        tol = _TOL_ATR * _atr(m5)
        price = m5[-1].close

        # A level further than this from the price is real but out of reach
        # today, and keeping it would spend one of the few slots per side on a
        # band the chart never draws. Measured against the last day of trading
        # range, so it scales itself per asset.
        day = m5[-_BARS_PER_DAY:]
        reach = _MAX_REACH_DAYS * (max(b.high for b in day) - min(b.low for b in day))

        zones: list[PriceZone] = []
        for zone in _merge_zones(clusters, tol):
            mid = (zone.low + zone.high) / 2
            if reach > 0 and abs(mid - price) > reach:
                continue
            zones.append(
                PriceZone(
                    symbol=symbol,
                    low=zone.low,
                    high=zone.high,
                    side="sell" if mid > price else "buy",
                    kind=zone.kind,
                    touches=zone.touches,
                    timeframes=zone.timeframes,
                    score=zone.score,
                    strength=round(min(1.0, zone.score / _FULL_SCORE), 3),
                    last_touch=zone.last_touch,
                    distance_pct=round((mid - price) / price * 100, 3) if price else 0.0,
                )
            )

        # Cap per side, keeping the strongest — and among equals the nearest,
        # because a zone price can actually reach is the one worth drawing.
        # A weaker zone sitting within `tol` of one already kept is dropped:
        # merging only joins bands that OVERLAP, so three separate levels a
        # couple of points apart would otherwise draw as three stripes and the
        # chart stops being readable. The strongest of the group speaks for it.
        out: list[PriceZone] = []
        for side in ("buy", "sell"):
            kept: list[PriceZone] = []
            ranked = sorted(
                (z for z in zones if z.side == side),
                key=lambda z: (-z.score, abs(z.distance_pct)),
            )
            for zone in ranked:
                if any(zone.low <= k.high + tol and zone.high >= k.low - tol for k in kept):
                    continue
                kept.append(zone)
                if len(kept) == _MAX_PER_SIDE:
                    break
            out += kept
        return sorted(out, key=lambda z: z.low)
