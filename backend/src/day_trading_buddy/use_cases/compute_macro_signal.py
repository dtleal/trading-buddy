"""Compute the macro sub-score per asset.

Heuristics for MVP:
- Rising 10Y yield is bearish for both stocks and Gold (-10).
- Falling 10Y yield is bullish for both (+10).
- Stronger dollar (DXY proxy DTWEXBGS up) is bearish for Gold (-10) and mildly
  bearish for SPX/USTEC (-3).
- FedWatch swing toward cuts is bullish (+10 for stocks, +5 for Gold); swing
  toward hikes is bearish.
"""

from __future__ import annotations

from dataclasses import dataclass

from day_trading_buddy.core.enums import AssetSymbol
from day_trading_buddy.core.models import MacroSnapshot


@dataclass(frozen=True)
class MacroBias:
    score: float
    rationale: list[str]


def _delta_sign(delta: float | None, threshold: float = 0.01) -> int:
    if delta is None:
        return 0
    if delta > threshold:
        return 1
    if delta < -threshold:
        return -1
    return 0


class ComputeMacroSignalUseCase:
    """Pure compute. Maps macro indicators → per-asset bias score."""

    async def execute(self, snapshot: MacroSnapshot) -> dict[AssetSymbol, MacroBias]:
        results: dict[AssetSymbol, MacroBias] = {}

        ten_year = snapshot.indicators.get("DGS10")
        dxy = snapshot.indicators.get("DTWEXBGS")

        for asset in AssetSymbol:
            score = 50.0
            rationale: list[str] = []
            is_stock = asset in {AssetSymbol.USTEC, AssetSymbol.SPX}

            if ten_year is not None:
                sign = _delta_sign(ten_year.delta_1w, threshold=0.05)
                if sign > 0:
                    score -= 10
                    rationale.append("10Y yield rising week-over-week")
                elif sign < 0:
                    score += 10
                    rationale.append("10Y yield falling week-over-week")

            if dxy is not None:
                sign = _delta_sign(dxy.delta_1w, threshold=0.2)
                if asset == AssetSymbol.GOLD:
                    if sign > 0:
                        score -= 10
                        rationale.append("DXY rising (USD strength)")
                    elif sign < 0:
                        score += 8
                        rationale.append("DXY falling (USD weakness)")
                elif is_stock and sign > 0:
                    score -= 3
                    rationale.append("DXY rising mildly bearish for stocks")

            fw = snapshot.fedwatch
            if fw is not None:
                cut_weight = fw.cut_50 + fw.cut_25
                hike_weight = fw.hike_25 + fw.hike_50
                if cut_weight > hike_weight + 0.2:
                    bonus = 10 if is_stock else 5
                    score += bonus
                    rationale.append("FedWatch leans toward rate cuts")
                elif hike_weight > cut_weight + 0.2:
                    penalty = 10 if is_stock else 3
                    score -= penalty
                    rationale.append("FedWatch leans toward rate hikes")

            score = max(0.0, min(100.0, score))
            results[asset] = MacroBias(score=score, rationale=rationale)

        return results
