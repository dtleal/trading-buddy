"""Heuristic detector for high-confluence intraday trade setups.

This use case turns multiple objective conditions into a single TradeSetup
"with edge" — or returns None when the market is not offering a clear edge.

Design constraints:
- Pure function. No I/O. Easy to unit test.
- Conservative by default. False negatives (missed signals) are preferred over
  false positives (forced signals). The user is trading their own money.
- Every emitted setup carries a rationale (list of strings) so the user can
  judge whether the heuristic's reasoning matches their read of the tape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.enums import AssetSymbol, BiasLevel
from core.models import BiasReport, IntradayLevels, TradeSetup


@dataclass(frozen=True)
class SetupThresholds:
    """Tunable knobs. Keep defaults conservative."""

    min_score_long: float = 60.0  # bias score >= this for LONG edge
    max_score_short: float = 40.0  # bias score <= this for SHORT edge
    min_risk_reward: float = 2.0  # required reward/risk
    pullback_atr_window: float = 0.75  # price within N*ATR of nearest mean
    target_atr_window: float = 4.0  # max target distance in ATR if no PDH/PDL


class DetectTradeSetupUseCase:
    """Pure heuristic. `execute(levels, bias)` → TradeSetup | None."""

    def __init__(self, thresholds: SetupThresholds | None = None) -> None:
        self._t = thresholds or SetupThresholds()

    def execute(self, levels: IntradayLevels, bias: BiasReport) -> TradeSetup | None:
        # Requires enough intraday data to be meaningful.
        if not _has_required_intraday(levels):
            return None

        if bias.score >= self._t.min_score_long:
            return self._try_long(levels, bias)
        if bias.score <= self._t.max_score_short:
            return self._try_short(levels, bias)
        # LATERAL: no edge by design.
        return None

    # --- LONG ---------------------------------------------------------------

    def _try_long(self, lv: IntradayLevels, bias: BiasReport) -> TradeSetup | None:
        last = lv.last_price
        # Required confluences for an objective long edge.
        if not (lv.ema_200 is not None and last > lv.ema_200):
            return None
        if not (lv.sma_200 is not None and last > lv.sma_200):
            return None
        if not (lv.vwap is not None and last > lv.vwap):
            return None
        if not (lv.atr_14 is not None and lv.atr_14 > 0):
            return None
        if lv.last_swing_low is None:
            return None

        # Pullback condition: price within pullback_atr_window of EMA 9 or VWAP.
        # i.e., we are NOT chasing a vertical move — we are near a mean reversion zone.
        atr = lv.atr_14
        nearest_pullback = _nearest_value_below(last, (lv.ema_9, lv.ema_20, lv.vwap))
        if nearest_pullback is None:
            return None
        if (last - nearest_pullback) > self._t.pullback_atr_window * atr:
            return None  # too extended above the mean

        # Stop: below last swing low minus a small buffer (0.25 ATR).
        stop = lv.last_swing_low - 0.25 * atr
        risk = last - stop
        if risk <= 0:
            return None

        # Target: prefer PDH if present and above last; else swing-based; else 3xATR
        target = _pick_long_target(lv, last, atr, self._t.target_atr_window)
        if target is None:
            return None
        reward = target - last
        if reward <= 0:
            return None

        rr = reward / risk
        if rr < self._t.min_risk_reward:
            return None

        rationale = [
            f"Score combinado {bias.score:.0f} ≥ {self._t.min_score_long:.0f} (viés estrutural ALTA).",
            "Preço acima de EMA 200, SMA 200 e VWAP — compradores no controle do dia.",
            f"Pullback até {nearest_pullback:.2f} dentro de {self._t.pullback_atr_window:.2f}×ATR (não está chasing).",
            f"R:R = {rr:.2f} (alvo {target:.2f} / stop {stop:.2f}).",
        ]
        return TradeSetup(
            asset=bias.asset,
            direction="LONG",
            trend_label=_trend_label_long(bias.level),
            continuation_label=_continuation_label(rr, bias.score, direction="LONG"),
            entry_zone_low=nearest_pullback,
            entry_zone_high=last,
            stop_level=stop,
            target_level=target,
            risk_reward=rr,
            rationale=rationale,
        )

    # --- SHORT --------------------------------------------------------------

    def _try_short(self, lv: IntradayLevels, bias: BiasReport) -> TradeSetup | None:
        last = lv.last_price
        if not (lv.ema_200 is not None and last < lv.ema_200):
            return None
        if not (lv.sma_200 is not None and last < lv.sma_200):
            return None
        if not (lv.vwap is not None and last < lv.vwap):
            return None
        if not (lv.atr_14 is not None and lv.atr_14 > 0):
            return None
        if lv.last_swing_high is None:
            return None

        atr = lv.atr_14
        nearest_pullback = _nearest_value_above(last, (lv.ema_9, lv.ema_20, lv.vwap))
        if nearest_pullback is None:
            return None
        if (nearest_pullback - last) > self._t.pullback_atr_window * atr:
            return None

        stop = lv.last_swing_high + 0.25 * atr
        risk = stop - last
        if risk <= 0:
            return None

        target = _pick_short_target(lv, last, atr, self._t.target_atr_window)
        if target is None:
            return None
        reward = last - target
        if reward <= 0:
            return None

        rr = reward / risk
        if rr < self._t.min_risk_reward:
            return None

        rationale = [
            f"Score combinado {bias.score:.0f} ≤ {self._t.max_score_short:.0f} (viés estrutural BAIXA).",
            "Preço abaixo de EMA 200, SMA 200 e VWAP — vendedores no controle do dia.",
            f"Pullback até {nearest_pullback:.2f} dentro de {self._t.pullback_atr_window:.2f}×ATR (não está chasing).",
            f"R:R = {rr:.2f} (alvo {target:.2f} / stop {stop:.2f}).",
        ]
        return TradeSetup(
            asset=bias.asset,
            direction="SHORT",
            trend_label=_trend_label_short(bias.level),
            continuation_label=_continuation_label(rr, 100.0 - bias.score, direction="SHORT"),
            entry_zone_low=last,
            entry_zone_high=nearest_pullback,
            stop_level=stop,
            target_level=target,
            risk_reward=rr,
            rationale=rationale,
        )


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _has_required_intraday(lv: IntradayLevels) -> bool:
    needed = (lv.atr_14, lv.ema_200, lv.sma_200, lv.vwap)
    return all(v is not None for v in needed)


def _nearest_value_below(price: float, candidates: tuple[float | None, ...]) -> float | None:
    """Closest finite value at or below `price`; None if none qualify."""
    valids = [c for c in candidates if c is not None and c <= price]
    return max(valids) if valids else None


def _nearest_value_above(price: float, candidates: tuple[float | None, ...]) -> float | None:
    valids = [c for c in candidates if c is not None and c >= price]
    return min(valids) if valids else None


def _pick_long_target(lv: IntradayLevels, last: float, atr: float, max_atr: float) -> float | None:
    candidates: list[float] = []
    if lv.pdh is not None and lv.pdh > last:
        candidates.append(lv.pdh)
    if lv.hod is not None and lv.hod > last:
        candidates.append(lv.hod)
    if lv.last_swing_high is not None and lv.last_swing_high > last:
        candidates.append(lv.last_swing_high)
    # ATR ceiling fallback
    candidates.append(last + max_atr * atr)
    return min(candidates) if candidates else None


def _pick_short_target(lv: IntradayLevels, last: float, atr: float, max_atr: float) -> float | None:
    candidates: list[float] = []
    if lv.pdl is not None and lv.pdl < last:
        candidates.append(lv.pdl)
    if lv.lod is not None and lv.lod < last:
        candidates.append(lv.lod)
    if lv.last_swing_low is not None and lv.last_swing_low < last:
        candidates.append(lv.last_swing_low)
    candidates.append(last - max_atr * atr)
    return max(candidates) if candidates else None


def _trend_label_long(level: BiasLevel) -> str:
    return {
        BiasLevel.BULLISH: "tendência alta forte",
        BiasLevel.NEUTRAL: "tendência alta moderada",
        BiasLevel.BEARISH: "tendência alta (divergente do bias)",
    }.get(level, "tendência alta")


def _trend_label_short(level: BiasLevel) -> str:
    return {
        BiasLevel.BEARISH: "tendência baixa forte",
        BiasLevel.NEUTRAL: "tendência baixa moderada",
        BiasLevel.BULLISH: "tendência baixa (divergente do bias)",
    }.get(level, "tendência baixa")


def _continuation_label(rr: float, confidence: float, direction: Literal["LONG", "SHORT"]) -> str:
    if rr >= 3.0 and confidence >= 70:
        return "alta probabilidade de continuação"
    if rr >= 2.5 or confidence >= 65:
        return "boa probabilidade de continuação"
    return "probabilidade média de continuação"
