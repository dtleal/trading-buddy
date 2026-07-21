"""Unit tests for the VIX×price stance matrix (`AssessVixPriceUseCase`)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.enums import AssetSymbol, TermStructure, VixRegime
from core.models import IntradayBar, VixSnapshot
from use_cases.assess_vix_price import AssessVixPriceUseCase

NOW = datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)


def _bars(
    closes: list[float], *, spread: float = 0.0, body: float | None = None
) -> list[IntradayBar]:
    """Build synthetic 5m bars from a close path.

    `spread` widens high/low beyond the open/close extremes (range without
    body); `body` overrides the |close-open| distance (defaults to the actual
    close-to-close move) so tests can force small-body/overlapping candles.
    """
    bars: list[IntradayBar] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev if body is None else c - body * (1 if c >= prev else -1)
        hi = max(o, c) + spread
        lo = min(o, c) - spread
        bars.append(
            IntradayBar(
                timestamp=NOW - timedelta(minutes=5 * (len(closes) - i)),
                open=o,
                high=hi,
                low=lo,
                close=c,
                volume=100.0,
            )
        )
        prev = c
    return bars


def _vix_snapshot(value: float, regime: VixRegime) -> VixSnapshot:
    return VixSnapshot(
        vix=value, vix9d=value, vix3m=value, regime=regime, term_structure=TermStructure.FLAT
    )


def _flat_then_ramp(base: float, n_flat: int, ramp: list[float]) -> list[float]:
    return [base] * n_flat + ramp


def _alternating(center: float, amp: float, n: int, drift: float = 0.0) -> list[float]:
    """Closes that alternate up/down around a (optionally drifting) center."""
    out = []
    for i in range(n):
        c = center + drift * i + (amp if i % 2 == 0 else -amp)
        out.append(c)
    return out


UC = AssessVixPriceUseCase()


class TestVixSide:
    def test_no_vix_bars_yields_empty(self) -> None:
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(20.0, VixRegime.MID),
            vix_bars=[],
            bars_by_asset={AssetSymbol.USTEC: _bars([100.0] * 40)},
        )
        assert result == {}

    def test_insufficient_price_bars_skips_asset(self) -> None:
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(20.0, VixRegime.MID),
            vix_bars=_bars([20.0] * 30),
            bars_by_asset={AssetSymbol.USTEC: _bars([100.0] * 5)},
        )
        assert result == {}


class TestSpike:
    def test_vix_spike_means_sell_rallies_and_exit_longs(self) -> None:
        # VIX jumps 22 → 26 in the last half hour (spike) with price drifting up
        # into the upper band → "não compre, venda o repique" + trigger.
        vix_closes = _flat_then_ramp(22.0, 40, [22.5, 23.5, 24.5, 25.2, 25.8, 26.4])
        price = _bars(list(range(100, 140)), spread=0.1)  # steady climb → %B high
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(26.4, VixRegime.HIGH),
            vix_bars=_bars(vix_closes),
            bars_by_asset={AssetSymbol.USTEC: price},
        )
        sig = result[AssetSymbol.USTEC]
        assert sig.stance == "sell_rallies"
        assert sig.caution == "exit_longs"
        assert sig.trigger is True  # already at the upper band


class TestUserScenario:
    def test_mild_vix_rise_plus_weak_downtrend_sells_the_tops(self) -> None:
        # The exact read requested: VIX in a mild uptrend, price in a WEAK 5m
        # downtrend with small overlapping candles bouncing between the bands,
        # currently at the top of the range → sell that top.
        vix_closes = [20.0 + 0.04 * i for i in range(40)]  # slow grind up (~+2.4%/h)
        # Price alternates ±3 around a falling center, ending on an up-swing
        # (at the top of the mini-range).
        closes = _alternating(1000.0, 3.0, 40, drift=-0.4)
        price = _bars(closes, spread=1.0, body=0.5)  # small bodies, wide wicks
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(vix_closes[-1], VixRegime.MID),
            vix_bars=_bars(vix_closes),
            bars_by_asset={AssetSymbol.USTEC: price},
        )
        sig = result[AssetSymbol.USTEC]
        assert sig.stance == "sell_rallies"
        assert sig.weak_trend is True
        assert sig.vix_trend == "rising"

    def test_fragile_rally_cautions_exit_longs(self) -> None:
        # Price rising WITH the VIX rising → close longs, no fresh entries.
        vix_closes = [20.0 + 0.06 * i for i in range(40)]
        price = _bars([1000.0 + 2.0 * i for i in range(40)], spread=0.2)
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(vix_closes[-1], VixRegime.MID),
            vix_bars=_bars(vix_closes),
            bars_by_asset={AssetSymbol.USTEC: price},
        )
        sig = result[AssetSymbol.USTEC]
        assert sig.stance == "neutral"
        assert sig.caution == "exit_longs"


class TestRelief:
    def test_vix_falling_buys_dips(self) -> None:
        vix_closes = [26.0 - 0.08 * i for i in range(40)]  # rolling over
        # Price recovering; last close pulled back to the lower band.
        closes = [1000.0 + 1.5 * i for i in range(39)] + [1020.0]
        price = _bars(closes, spread=0.2)
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(vix_closes[-1], VixRegime.MID),
            vix_bars=_bars(vix_closes),
            bars_by_asset={AssetSymbol.USTEC: price},
        )
        sig = result[AssetSymbol.USTEC]
        assert sig.stance == "buy_dips"
        assert sig.vix_trend == "falling"
        assert sig.trigger is True  # pullback reached the buy zone

    def test_vix_falling_with_price_falling_cautions_exit_shorts(self) -> None:
        vix_closes = [26.0 - 0.08 * i for i in range(40)]
        price = _bars([1000.0 - 2.0 * i for i in range(40)], spread=0.2)
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(vix_closes[-1], VixRegime.MID),
            vix_bars=_bars(vix_closes),
            bars_by_asset={AssetSymbol.USTEC: price},
        )
        sig = result[AssetSymbol.USTEC]
        assert sig.caution == "exit_shorts"


class TestChop:
    def test_low_flat_vix_narrow_bands_stays_out(self) -> None:
        vix_closes = [13.0] * 40
        # Long normal-width history, then a tight overlapping coil at the end.
        closes = _alternating(1000.0, 8.0, 50) + _alternating(1000.0, 0.5, 30)
        price = _bars(closes, spread=0.3, body=0.2)
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(13.0, VixRegime.LOW),
            vix_bars=_bars(vix_closes),
            bars_by_asset={AssetSymbol.USTEC: price},
        )
        sig = result[AssetSymbol.USTEC]
        assert sig.stance == "stay_out"
        assert sig.chop is True


class TestGoldInversion:
    def test_rising_vix_supports_gold(self) -> None:
        # Rising VIX + gold trending up → for gold that's the buy-dips side,
        # never the fragile-rally caution the indices get.
        vix_closes = [20.0 + 0.06 * i for i in range(40)]
        price = _bars([3300.0 + 1.0 * i for i in range(40)], spread=0.2)
        result = UC.execute(
            now=NOW,
            vix=_vix_snapshot(vix_closes[-1], VixRegime.MID),
            vix_bars=_bars(vix_closes),
            bars_by_asset={AssetSymbol.GOLD: price},
        )
        sig = result[AssetSymbol.GOLD]
        assert sig.stance == "buy_dips"
        assert sig.caution is None
        assert any("invertida" in r for r in sig.rationale)
