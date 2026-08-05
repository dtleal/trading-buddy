"""Combine technical / macro / sentiment sub-scores into the final bias report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from core.enums import TRACKED_ASSETS, AssetSymbol, BiasLevel
from core.models import BiasComponents, BiasReport
from use_cases.compute_macro_signal import MacroBias
from use_cases.compute_news_sentiment import SentimentBias
from use_cases.compute_technical_bias import TechnicalBias


@dataclass(frozen=True)
class BiasWeights:
    technical: float
    macro: float
    sentiment: float


@dataclass(frozen=True)
class BiasThresholds:
    bullish: float  # inclusive lower bound for BULLISH
    bearish: float  # inclusive upper bound for BEARISH


class ComputeCombinedBiasUseCase:
    """Pure compute. Weighted average → discrete `BiasLevel`."""

    def __init__(self, weights: BiasWeights, thresholds: BiasThresholds) -> None:
        self._weights = weights
        self._thresholds = thresholds

    def _level(self, score: float) -> BiasLevel:
        if score >= self._thresholds.bullish:
            return BiasLevel.BULLISH
        if score <= self._thresholds.bearish:
            return BiasLevel.BEARISH
        return BiasLevel.NEUTRAL

    async def execute(
        self,
        *,
        technical: dict[AssetSymbol, TechnicalBias],
        macro: dict[AssetSymbol, MacroBias],
        sentiment: dict[AssetSymbol, SentimentBias],
    ) -> dict[AssetSymbol, BiasReport]:
        timestamp = datetime.now(timezone.utc)
        reports: dict[AssetSymbol, BiasReport] = {}

        for asset in TRACKED_ASSETS:
            tech = technical.get(asset)
            mac = macro.get(asset)
            sen = sentiment.get(asset)

            tech_score = tech.score if tech else 50.0
            mac_score = mac.score if mac else 50.0
            sen_score = sen.score if sen else 50.0

            score = (
                tech_score * self._weights.technical
                + mac_score * self._weights.macro
                + sen_score * self._weights.sentiment
            )
            rationale: list[str] = []
            if tech:
                rationale.extend(f"[tech] {r}" for r in tech.rationale)
            if mac:
                rationale.extend(f"[macro] {r}" for r in mac.rationale)
            if sen:
                rationale.extend(f"[news] {r}" for r in sen.rationale)

            reports[asset] = BiasReport(
                asset=asset,
                timestamp=timestamp,
                score=score,
                level=self._level(score),
                components=BiasComponents(
                    technical=tech_score,
                    macro=mac_score,
                    sentiment=sen_score,
                ),
                rationale=rationale,
            )

        return reports
