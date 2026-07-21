"""Correlate the VIX 5m path with each asset's 5m price action into a stance.

The trader's question this answers: given where implied vol is AND what the 5m
tape looks like, should I be buying dips, selling rallies, staying out — or
closing what I already have open? The reads it encodes:

  - VIX stretched near the top of its recent range and still rising → don't
    buy; wait for a rally into the upper Bollinger band and sell it.
  - VIX drifting up while price grinds down in small, overlapping candles
    oscillating between the Bollinger bands → sell the tops of that range.
  - VIX rolling over from a spike → relief; buy pullbacks to the lower band.
  - Price rising WITH the VIX rising → fragile rally; close longs.
  - Price falling WITH the VIX falling → selloff losing fuel; close shorts.
  - VIX low and dead-flat, narrow bands, overlapping candles → no energy,
    stay out.

`execute()` is a pure function over already-fetched bars — no I/O, trivially
unit-testable. Gold is the risk-off asset: a rising VIX *supports* it, so the
VIX direction is inverted before the matrix is applied (and the inversion is
spelled out in the rationale).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import fmean, median, pstdev
from typing import Mapping, Sequence

from core.enums import AssetSymbol, VixRegime
from core.models import (
    IntradayBar,
    PriceTrendDir,
    VixCaution,
    VixPriceSignal,
    VixSnapshot,
    VixStance,
    VixTrendDir,
)

# Assets where a rising VIX is a tailwind, not a headwind (flight to safety).
_RISK_OFF_ASSETS = {AssetSymbol.GOLD}

_TREND_PT = {"up": "alta", "down": "baixa", "flat": "lateral"}


@dataclass(frozen=True)
class VixPriceThresholds:
    """Tunable knobs. Defaults sized for 5m bars (12 bars = 1 hour)."""

    # VIX side
    vix_trend_bars: int = 12  # window for the rising/falling read (~1h)
    vix_flat_band_pct: float = 1.5  # |Δ%| under this over the window = flat
    vix_spike_bars: int = 6  # fast-jump window (~30 min)
    vix_spike_pct: float = 5.0  # Δ% over spike window that counts as a spike
    vix_top_range_pos: float = 0.75  # position in lookback range that reads "no topo"

    # Price side (5m)
    bb_period: int = 20
    bb_stdev: float = 2.0
    sell_zone_pct_b: float = 0.75  # %B at/above → rally into the upper band
    buy_zone_pct_b: float = 0.25  # %B at/below → dip into the lower band
    slope_bars: int = 6  # SMA20 slope window for the trend read
    price_flat_band_pct: float = 0.06  # |SMA20 slope %| under this = flat
    candle_window: int = 8  # candles inspected for the weak/chop read
    weak_body_ratio: float = 0.5  # median body/range under this = small bodies
    flip_ratio: float = 0.5  # direction flips over window ≥ this = overlapping
    width_baseline_bars: int = 60  # rolling widths sampled for the narrow read
    narrow_width_vs_median: float = 0.75  # width under this × median = squeezed


@dataclass(frozen=True)
class _VixFeatures:
    value: float
    trend: VixTrendDir
    change_pct: float
    spike: bool
    range_pos: float | None


@dataclass(frozen=True)
class _PriceFeatures:
    trend: PriceTrendDir
    weak: bool
    chop: bool
    pct_b: float
    width_pct: float
    narrow: bool


class AssessVixPriceUseCase:
    """Pure assessor. Inject thresholds; call `execute(...)` per tick."""

    def __init__(self, thresholds: VixPriceThresholds | None = None) -> None:
        self._t = thresholds or VixPriceThresholds()

    def execute(
        self,
        *,
        now: datetime,
        vix: VixSnapshot | None,
        vix_bars: Sequence[IntradayBar],
        bars_by_asset: Mapping[AssetSymbol, Sequence[IntradayBar]],
    ) -> dict[AssetSymbol, VixPriceSignal]:
        vf = self._vix_features(vix_bars)
        if vf is None:
            return {}

        out: dict[AssetSymbol, VixPriceSignal] = {}
        for asset, bars in bars_by_asset.items():
            pf = self._price_features(bars)
            if pf is None:
                continue
            out[asset] = self._decide(asset, now, vix, vf, pf)
        return out

    # --- feature extraction --------------------------------------------------

    def _vix_features(self, bars: Sequence[IntradayBar]) -> _VixFeatures | None:
        t = self._t
        closes = [b.close for b in bars]
        if len(closes) < t.vix_trend_bars + 1:
            return None

        last = closes[-1]
        ref = closes[-1 - t.vix_trend_bars]
        change_pct = (last - ref) / ref * 100.0 if ref else 0.0
        trend: VixTrendDir = (
            "rising"
            if change_pct > t.vix_flat_band_pct
            else "falling" if change_pct < -t.vix_flat_band_pct else "flat"
        )

        spike = False
        if len(closes) > t.vix_spike_bars:
            fast_ref = closes[-1 - t.vix_spike_bars]
            if fast_ref:
                spike = (last - fast_ref) / fast_ref * 100.0 >= t.vix_spike_pct

        lo, hi = min(closes), max(closes)
        range_pos = (last - lo) / (hi - lo) if hi > lo else None

        return _VixFeatures(
            value=last, trend=trend, change_pct=change_pct, spike=spike, range_pos=range_pos
        )

    def _price_features(self, bars: Sequence[IntradayBar]) -> _PriceFeatures | None:
        t = self._t
        need = t.bb_period + t.slope_bars
        if len(bars) < need:
            return None
        closes = [b.close for b in bars]

        mid, upper, lower = _bollinger(closes, t.bb_period, t.bb_stdev)
        band = upper - lower
        pct_b = (closes[-1] - lower) / band if band > 0 else 0.5
        width_pct = band / mid * 100.0 if mid else 0.0

        # Is the band squeezed vs its own recent norm? (scale-free per asset)
        widths: list[float] = []
        start = max(t.bb_period, len(closes) - t.width_baseline_bars)
        for end in range(start, len(closes) + 1):
            m, u, lo_ = _bollinger(closes[:end], t.bb_period, t.bb_stdev)
            if m:
                widths.append((u - lo_) / m * 100.0)
        narrow = bool(widths) and width_pct < t.narrow_width_vs_median * median(widths)

        # Trend: slope of the SMA20 over the last few bars, in %.
        sma_now = fmean(closes[-t.bb_period :])
        sma_prev = fmean(closes[-t.bb_period - t.slope_bars : -t.slope_bars])
        slope_pct = (sma_now - sma_prev) / sma_prev * 100.0 if sma_prev else 0.0
        trend: PriceTrendDir = (
            "up"
            if slope_pct > t.price_flat_band_pct
            else "down" if slope_pct < -t.price_flat_band_pct else "flat"
        )

        # Candle quality: small bodies and/or alternating buyer/seller candles.
        window = bars[-t.candle_window :]
        ratios = [abs(b.close - b.open) / (b.high - b.low) for b in window if b.high > b.low]
        small_bodies = bool(ratios) and median(ratios) < t.weak_body_ratio
        signs = [1 if b.close > b.open else -1 for b in window if b.close != b.open]
        flips = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
        alternating = len(signs) > 1 and flips / (len(signs) - 1) >= t.flip_ratio
        weak = small_bodies or alternating

        return _PriceFeatures(
            trend=trend,
            weak=weak,
            chop=weak and trend == "flat",
            pct_b=pct_b,
            width_pct=width_pct,
            narrow=narrow,
        )

    # --- the matrix ------------------------------------------------------------

    def _decide(
        self,
        asset: AssetSymbol,
        now: datetime,
        vix: VixSnapshot | None,
        v: _VixFeatures,
        p: _PriceFeatures,
    ) -> VixPriceSignal:
        t = self._t
        invert = asset in _RISK_OFF_ASSETS
        # For the risk-off asset a rising VIX plays the role a falling VIX plays
        # for the indices — flip the direction fed to the matrix. A spike loses
        # its "get out" meaning there, so it is only honored on risk-on assets.
        eff_trend: VixTrendDir = (
            v.trend
            if not invert
            else "falling" if v.trend == "rising" else "rising" if v.trend == "falling" else "flat"
        )
        eff_spike = v.spike and not invert
        at_top = v.range_pos is not None and v.range_pos >= t.vix_top_range_pos
        regime = vix.regime if vix is not None else None

        stance: VixStance = "neutral"
        caution: VixCaution | None = None
        trigger = False

        if eff_spike or (regime is VixRegime.HIGH and eff_trend == "rising"):
            stance = "sell_rallies"
            caution = "exit_longs"
            headline = "VIX esticado e subindo — não compre. Espere o repique e venda o topo."
            trigger = p.pct_b >= t.sell_zone_pct_b
        elif eff_trend == "rising" and p.trend == "up":
            headline = "Preço subindo com VIX subindo — rally frágil, considere encerrar compras."
            caution = "exit_longs"
        elif eff_trend == "rising":
            stance = "sell_rallies"
            if p.trend == "down":
                caution = "exit_longs"
            if p.weak:
                headline = "VIX em alta leve + baixa fraca no 5m (candles sobrepostos) — venda os topos do range."
            else:
                headline = "VIX subindo com preço cedendo — venda repiques."
            trigger = p.pct_b >= t.sell_zone_pct_b
        elif eff_trend == "falling" and p.trend == "down":
            headline = "Queda perdendo combustível (VIX cedendo) — considere encerrar vendas."
            caution = "exit_shorts"
        elif eff_trend == "falling":
            stance = "buy_dips"
            headline = (
                "VIX devolvendo do topo — alívio; compre recuos."
                if at_top
                else "VIX caindo — compre recuos."
            )
            trigger = p.pct_b <= t.buy_zone_pct_b
        else:  # flat VIX: the tape decides
            if regime is VixRegime.LOW and p.narrow and p.weak:
                stance = "stay_out"
                headline = "Sem energia: VIX baixo e parado, bandas estreitas, candles sobrepostos — fique de fora."
            elif p.trend == "up":
                stance = "buy_dips"
                headline = "VIX estável com preço em alta — compre recuos."
                trigger = p.pct_b <= t.buy_zone_pct_b
            elif p.trend == "down":
                stance = "sell_rallies"
                headline = "VIX estável com preço em baixa — venda repiques."
                trigger = p.pct_b >= t.sell_zone_pct_b
            else:
                headline = "Sem leitura direcional — VIX parado e preço lateral."

        rationale = self._rationale(v, p, invert, stance, trigger)

        return VixPriceSignal(
            asset=asset,
            asof=now,
            stance=stance,
            caution=caution,
            trigger=trigger,
            headline=headline,
            rationale=rationale,
            vix_value=v.value,
            vix_trend=v.trend,
            vix_change_pct=v.change_pct,
            vix_range_pos=v.range_pos,
            price_trend=p.trend,
            weak_trend=p.weak,
            bb_pos=p.pct_b,
            bb_width_pct=p.width_pct,
            chop=p.chop,
        )

    def _rationale(
        self,
        v: _VixFeatures,
        p: _PriceFeatures,
        invert: bool,
        stance: VixStance,
        trigger: bool,
    ) -> list[str]:
        lines: list[str] = []
        vix_line = f"VIX {v.value:.1f} ({v.change_pct:+.1f}% na última hora)"
        if v.spike:
            vix_line += " — spike"
        if v.range_pos is not None:
            vix_line += f", a {v.range_pos * 100:.0f}% do range recente"
        lines.append(vix_line)

        price_line = f"5m: tendência {_TREND_PT[p.trend]}"
        if p.weak:
            price_line += ", candles pequenos/sobrepostos"
        price_line += f" · %B {p.pct_b:.2f} · bandas {p.width_pct:.2f}%"
        if p.narrow:
            price_line += " (estreitas)"
        lines.append(price_line)

        if invert:
            lines.append("Ouro: VIX subindo = busca por proteção — leitura invertida")
        if trigger:
            zone = (
                "superior — zona de VENDA"
                if stance == "sell_rallies"
                else "inferior — zona de COMPRA"
            )
            lines.append(f"Preço na banda {zone} agora")
        return lines


def _bollinger(closes: Sequence[float], period: int, k: float) -> tuple[float, float, float]:
    """(middle, upper, lower) of the last `period` closes."""
    tail = closes[-period:]
    mid = fmean(tail)
    sd = pstdev(tail)
    return mid, mid + k * sd, mid - k * sd


__all__ = ["AssessVixPriceUseCase", "VixPriceThresholds"]
