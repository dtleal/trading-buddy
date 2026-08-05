"""Compute the technical bias sub-score for each asset.

Pure function, no I/O. Inputs: a `MarketSnapshot`. Outputs: a per-asset score
in [0, 100], where 50 is neutral.

Rules (designed to be cheap to reason about and easy to tweak):
- Distance vs MA200 daily contributes +/- 25 points (linear, clipped at ±2%).
- VIX regime contributes a global tilt: LOW favours stocks (+5), HIGH penalises
  stocks (-10) and helps Gold (+5).
- VIX term structure: backwardation penalises stocks (-5), helps Gold (+3);
  contango is neutral / very slightly bullish for stocks (+2).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.enums import RISK_ON_ASSETS, AssetSymbol, TermStructure, VixRegime
from core.models import MarketSnapshot


@dataclass(frozen=True)
class TechnicalBias:
    score: float
    rationale: list[str]


class ComputeTechnicalBiasUseCase:
    """Pure compute. No constructor dependencies."""

    async def execute(self, snapshot: MarketSnapshot) -> dict[AssetSymbol, TechnicalBias]:
        return {asset: self._for_asset(asset, snapshot) for asset in snapshot.assets}

    def _for_asset(self, asset: AssetSymbol, snapshot: MarketSnapshot) -> TechnicalBias:
        score = 50.0
        rationale: list[str] = []

        quote = snapshot.assets[asset]
        if quote.ma200_d is not None and quote.ma200_d > 0:
            distance_pct = (quote.price - quote.ma200_d) / quote.ma200_d * 100.0
            contribution = max(-25.0, min(25.0, distance_pct * 12.5))  # ±2% → ±25
            score += contribution
            if distance_pct >= 0:
                rationale.append(f"price {distance_pct:+.1f}% above MA200 daily")
            else:
                rationale.append(f"price {distance_pct:+.1f}% below MA200 daily")

        # Risk-on assets move together vs the VIX: they rally in calm regimes
        # and get hit when fear spikes. That covers the stock indices and oil
        # (a fear spike hits demand). Gold is the odd one out — it tends to
        # catch a bid when stress rises.
        is_risk_on = asset in RISK_ON_ASSETS

        if snapshot.vix.regime == VixRegime.LOW:
            if is_risk_on:
                score += 5
                rationale.append("VIX low regime (risk-on)")
            else:
                rationale.append("VIX low regime")
        elif snapshot.vix.regime == VixRegime.HIGH:
            if is_risk_on:
                score -= 10
                rationale.append("VIX high regime (risk-off)")
            else:
                score += 5
                rationale.append("VIX high regime helps Gold")

        if snapshot.vix.term_structure == TermStructure.BACKWARDATION:
            if is_risk_on:
                score -= 5
                rationale.append("VIX backwardation (stress)")
            else:
                score += 3
                rationale.append("VIX backwardation lifts Gold")
        elif snapshot.vix.term_structure == TermStructure.CONTANGO and is_risk_on:
            score += 2
            rationale.append("VIX contango (calm)")

        score = max(0.0, min(100.0, score))
        return TechnicalBias(score=score, rationale=rationale)
