"""Unit tests for the empirical band-path scenario."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from core.enums import AssetSymbol
from core.models import IntradayBar
from use_cases.project_band_path import (
    BAND_PERIOD,
    HORIZON_BARS,
    project_band_path,
)

START = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)


def _bars(closes: list[float], *, wick: float = 0.0) -> list[IntradayBar]:
    """Bars from a close series. `wick` widens each bar's high/low so touches
    can be exercised independently of the closes."""
    return [
        IntradayBar(
            timestamp=START + timedelta(minutes=5 * i),
            open=c,
            high=c + wick,
            low=c - wick,
            close=c,
            volume=100.0,
        )
        for i, c in enumerate(closes)
    ]


def _sine(n: int, *, amplitude: float = 10.0, period: int = 24) -> list[float]:
    """A clean oscillation. NOTE: a smooth sine barely ever reaches a 2σ band
    (the band is computed from that same oscillation, so it is wider than the
    swing) — fine for symmetry checks, useless for touch statistics."""
    return [100.0 + amplitude * math.sin(2 * math.pi * i / period) for i in range(n)]


def _mean_reverting(n: int, *, seed: int = 7, pull: float = 0.05) -> list[float]:
    """Seeded mean-reverting walk (Ornstein-Uhlenbeck).

    Unlike a sine or a straight ramp, a noisy walk actually reaches its own 2σ
    bands, and the `pull` back to 100 is real mean reversion — so this is the
    series where "taps the lower band, comes back up" must show up.
    """
    rng = random.Random(seed)
    price = 100.0
    out = []
    for _ in range(n):
        price += pull * (100.0 - price) + rng.gauss(0.0, 1.0)
        out.append(price)
    return out


def test_returns_none_without_enough_bars() -> None:
    bars = _bars([100.0] * (BAND_PERIOD + HORIZON_BARS))
    assert project_band_path(AssetSymbol.USTEC, bars) is None


def test_returns_none_on_a_flat_series() -> None:
    # Zero band width: nothing to measure, and no division by zero either.
    bars = _bars([100.0] * 300)
    assert project_band_path(AssetSymbol.USTEC, bars) is None


def test_returns_none_when_the_sample_is_thin() -> None:
    # A single steady ramp never revisits the same spot in the band enough
    # times... but it does (pct_b is constant on a ramp), so force thinness
    # with an impossible sample floor instead.
    bars = _bars(_sine(400))
    assert project_band_path(AssetSymbol.USTEC, bars, min_samples=10_000) is None


def _scenario_at_bottom(closes: list[float]):
    """First scenario found (scanning back) with price low inside its band."""
    for cut in range(len(closes), BAND_PERIOD + HORIZON_BARS, -1):
        scen = project_band_path(AssetSymbol.USTEC, _bars(closes[:cut]))
        if scen is not None and scen.pct_b < 0.2:
            return scen
    return None


def _trending(n: int, *, seed: int = 11, drift: float = 0.25) -> list[float]:
    """Seeded walk with a steady climb and no pull back to any mean."""
    rng = random.Random(seed)
    price = 100.0
    out = []
    for _ in range(n):
        price += drift + rng.gauss(0.0, 1.0)
        out.append(price)
    return out


def test_route_from_the_bottom_of_the_band_leads_back_toward_the_middle() -> None:
    """Sitting at the bottom of a mean-reverting series: the lower band is what
    gets touched first, and the typical route from there heads back up."""
    scen = _scenario_at_bottom(_mean_reverting(1200))
    assert scen is not None
    assert scen.samples >= 12
    assert scen.lower_first is not None
    assert scen.lower_first.n > (scen.upper_first.n if scen.upper_first else 0)
    # The typical route leads UP — but only back toward the middle, not past it.
    assert scen.last_close < scen.path[-1].median <= scen.mid
    # The route covers the whole horizon and the cone brackets the median.
    assert [p.step for p in scen.path] == list(range(1, HORIZON_BARS + 1))
    assert all(p.p25 <= p.median <= p.p75 for p in scen.path)


def test_getting_back_to_the_middle_beats_reaching_the_opposite_band() -> None:
    """Coming back to the SMA is common; crossing the whole band in an hour is
    not — you cannot reach the far band without passing the middle first."""
    for closes in (_mean_reverting(1200), _trending(1200)):
        scen = _scenario_at_bottom(closes)
        assert scen is not None and scen.lower_first is not None
        assert scen.back_to_mid_pct > scen.lower_first.back_pct
        assert 0.0 <= scen.back_to_mid_pct <= 1.0


def _alternating(n: int = 200, swing: float = 0.5) -> list[float]:
    """Dead-quiet oscillation: flat middle band, steady width, no big candles."""
    return [100.0 + (swing if i % 2 else -swing) for i in range(n)]


def test_regime_reads_a_quiet_market_as_flat_and_steady() -> None:
    scen = project_band_path(AssetSymbol.USTEC, _bars(_alternating(), wick=0.2))
    assert scen is not None and scen.regime is not None
    assert scen.regime.trend == "flat"
    assert scen.regime.width == "steady"
    assert scen.regime.push == "none"


def test_regime_reads_a_steady_climb_as_an_uptrend() -> None:
    # Drift well above the noise, so this is an unambiguous trend rather than a
    # borderline one sitting on the threshold.
    scen = project_band_path(AssetSymbol.USTEC, _bars(_trending(600, drift=0.5), wick=0.2))
    assert scen is not None and scen.regime is not None
    assert scen.regime.trend == "up"


def test_regime_spots_a_giant_candle_trying_to_break_out() -> None:
    """One outsized candle at the end, same close — only the range changes."""
    bars = _bars(_alternating(), wick=0.2)
    last = bars[-1]
    pushed = bars[:-1] + [
        last.model_copy(
            update={
                "open": last.close - 1.5,
                "high": last.close + 0.2,
                "low": last.close - 1.7,
            }
        )
    ]
    quiet = project_band_path(AssetSymbol.USTEC, bars)
    driving = project_band_path(AssetSymbol.USTEC, pushed)
    assert quiet is not None and quiet.regime is not None
    assert driving is not None and driving.regime is not None
    assert quiet.regime.push == "none"
    assert driving.regime.push == "up"


def test_regime_spots_the_bands_widening() -> None:
    """A quiet stretch that suddenly starts swinging much harder."""
    closes = _alternating(150) + [100.0 + (3.0 if i % 2 else -3.0) for i in range(12)]
    scen = project_band_path(AssetSymbol.USTEC, _bars(closes, wick=0.2))
    assert scen is not None and scen.regime is not None
    assert scen.regime.width == "expanding"


def _quiet_then_trending(seed: int = 3) -> list[float]:
    """800 mean-reverting bars, then 400 of a steady climb."""
    rng = random.Random(seed)
    price = 100.0
    out = []
    for _ in range(800):
        price += 0.05 * (100.0 - price) + rng.gauss(0.0, 1.0)
        out.append(price)
    for _ in range(400):
        price += 0.5 + rng.gauss(0.0, 1.0)
        out.append(price)
    return out


def test_conditioning_on_the_trend_lowers_the_odds_of_coming_back() -> None:
    """Riding the top of the band in a climbing market is NOT the same as
    sitting there in a quiet one — and the number has to show it. Measured on a
    series whose second half trends: the overall figure mixes both phases, the
    conditioned one only counts the bars that were also trending up."""
    scen = project_band_path(AssetSymbol.USTEC, _bars(_quiet_then_trending(), wick=0.3))
    assert scen is not None and scen.regime is not None
    assert scen.regime.trend == "up"  # evaluated at the end of the trending half
    r = scen.return_to_mid
    assert r is not None
    assert r.pct < scen.back_to_mid_pct  # trend makes the snap-back rarer
    # Conditioning can only shrink the sample, never grow it.
    assert 0 < r.regime_n <= scen.samples
    assert r.median_bars is None or r.median_bars >= 1


def test_the_state_filter_relaxes_instead_of_going_silent() -> None:
    """A sample too thin for the full filter must fall back to fewer
    conditions (and say so) rather than report nothing."""
    bars = _bars(_quiet_then_trending(), wick=0.3)
    strict = project_band_path(AssetSymbol.USTEC, bars, min_samples=12)
    loose = project_band_path(AssetSymbol.USTEC, bars, min_samples=200)
    assert strict is not None and strict.return_to_mid is not None
    assert loose is not None and loose.return_to_mid is not None
    # A higher bar for "enough" forces a shorter list of held-constant filters.
    assert len(loose.return_to_mid.matched_on) < len(strict.return_to_mid.matched_on)
    assert loose.return_to_mid.regime_n > strict.return_to_mid.regime_n


def test_a_wide_band_is_reached_less_often_than_a_narrow_one() -> None:
    """What decides the band-to-band round trip is the band's width against how
    fast the market moves — NOT mean reversion. The mean-reverting series here
    has a band ~18 typical bar moves wide (unreachable inside a 12-bar horizon),
    the trending one ~7, so the trending one round-trips far more often."""
    wide = _scenario_at_bottom(_mean_reverting(1200))
    narrow = _scenario_at_bottom(_trending(1200))
    assert wide is not None and narrow is not None
    assert wide.lower_first is not None and narrow.lower_first is not None
    assert (wide.upper - wide.lower) > (narrow.upper - narrow.lower)
    assert narrow.lower_first.back_pct > wide.lower_first.back_pct


def test_mirrored_series_mirrors_the_verdict() -> None:
    """Flipping the series upside down must swap the two bands' roles."""
    closes = _sine(400)
    up = project_band_path(AssetSymbol.USTEC, _bars(closes))
    down = project_band_path(AssetSymbol.USTEC, _bars([200.0 - c for c in closes]))
    assert up is not None and down is not None
    assert up.pct_b == round(1.0 - down.pct_b, 12) or math.isclose(
        up.pct_b, 1.0 - down.pct_b, abs_tol=1e-9
    )
    assert math.isclose(up.touch_upper_pct, down.touch_lower_pct, abs_tol=1e-9)
    assert math.isclose(up.touch_lower_pct, down.touch_upper_pct, abs_tol=1e-9)


def test_touches_are_judged_on_wicks_not_closes() -> None:
    """A wick that reaches the band counts as a touch even if the close doesn't."""
    closes = _sine(400, amplitude=6.0)
    tight = project_band_path(AssetSymbol.USTEC, _bars(closes))
    wicky = project_band_path(AssetSymbol.USTEC, _bars(closes, wick=3.0))
    assert tight is not None and wicky is not None
    assert wicky.touch_upper_pct >= tight.touch_upper_pct
    assert wicky.touch_lower_pct >= tight.touch_lower_pct
    assert (wicky.touch_upper_pct + wicky.touch_lower_pct) > (
        tight.touch_upper_pct + tight.touch_lower_pct
    )
