"""Compute per-asset **intraday** bias from 5m structure.

Pure function. Anchored at 50 (neutral), the score moves up/down based on
price position relative to standard intraday references. Each reference
contributes a fixed weight — the resulting score is deterministic and the
contributing factors are surfaced via the `signals` field for tooltip use.

Scoring weights (single direction; symmetric for "below"):

  +30 if price > VWAP            — strongest intraday level on the day
  +20 if price > SMA 200 5m      — slow trend filter on 5m
  +20 if price > EMA 200 5m      — slow trend filter on 5m
  +15 if price > EMA 20 5m       — medium-term intraday
  +15 if price > EMA 9 5m        — short-term intraday
  -30 / -20 / -20 / -15 / -15    — mirrored for below

Sum range is -100 to +100, mapped to 0-100 by adding 50 and dividing by 2 →
neutral at 50, fully bullish at 100, fully bearish at 0. Same ALTA/BAIXA/
LATERAL thresholds as the daily score (≥60 / ≤40) for visual consistency.
"""

from __future__ import annotations

from core.enums import AssetSymbol, BiasLevel
from core.models import IntradayBiasReport, IntradayLevels

# (weight, attribute, human label) tuples — kept declarative so the rule
# set stays easy to audit.
_RULES: list[tuple[float, str, str]] = [
    (30.0, "vwap", "VWAP"),
    (20.0, "sma_200", "SMA 200 (5m)"),
    (20.0, "ema_200", "EMA 200 (5m)"),
    (15.0, "ema_20", "EMA 20 (5m)"),
    (15.0, "ema_9", "EMA 9 (5m)"),
]


def _bias_level(score: float) -> BiasLevel:
    if score >= 60.0:
        return BiasLevel.BULLISH
    if score <= 40.0:
        return BiasLevel.BEARISH
    return BiasLevel.NEUTRAL


class ComputeIntradayBiasUseCase:
    """`execute(asset, levels)` → IntradayBiasReport. No I/O."""

    def execute(
        self,
        asset: AssetSymbol,
        levels: IntradayLevels,
    ) -> IntradayBiasReport:
        last = levels.last_price

        # Apply each rule. Missing values contribute nothing and are
        # noted in the signals list so the user knows the score had less
        # data to work with (relevant in the first ~30 min of session).
        raw_score = 0.0
        signals: list[str] = []

        for weight, attr, label in _RULES:
            value = getattr(levels, attr, None)
            if value is None:
                signals.append(f"{label} indisponível")
                continue
            if last > value:
                raw_score += weight
                signals.append(f"acima {label}")
            elif last < value:
                raw_score -= weight
                signals.append(f"abaixo {label}")
            else:
                signals.append(f"em {label}")

        # Map [-100, +100] → [0, 100] centred at 50.
        score = max(0.0, min(100.0, 50.0 + raw_score / 2.0))

        return IntradayBiasReport(
            asset=asset,
            score=score,
            level=_bias_level(score),
            signals=signals,
        )
