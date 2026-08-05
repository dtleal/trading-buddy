"""Aggregate sentiment of recent news into a [0, 100] sub-score per asset.

For MVP we apply the same news bucket to every asset. A future refinement can
classify headlines by ticker/topic and route them per-asset.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from core.enums import TRACKED_ASSETS, AssetSymbol, SentimentLabel
from core.interfaces import SentimentClassifier
from core.models import NewsItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SentimentBias:
    score: float
    classified_count: int
    rationale: list[str]


class ComputeNewsSentimentUseCase:
    """Runs each headline through the classifier and averages the result."""

    def __init__(self, classifier: SentimentClassifier) -> None:
        self._classifier = classifier

    async def execute(self, items: list[NewsItem]) -> dict[AssetSymbol, SentimentBias]:
        if not items:
            neutral = SentimentBias(score=50.0, classified_count=0, rationale=["no recent news"])
            return {asset: neutral for asset in TRACKED_ASSETS}

        classifications = await asyncio.gather(
            *(self._classifier.classify(self._text_for(i)) for i in items)
        )

        positive = sum(1 for label, _ in classifications if label == SentimentLabel.POSITIVE)
        negative = sum(1 for label, _ in classifications if label == SentimentLabel.NEGATIVE)
        avg_score = sum(score for _, score in classifications) / len(classifications)

        # Map avg [-1.0, 1.0] → [0, 100] linearly.
        score = max(0.0, min(100.0, 50.0 + avg_score * 50.0))
        rationale = [
            f"news mix: {positive} positive / {negative} negative / "
            f"{len(classifications) - positive - negative} neutral"
        ]
        result = SentimentBias(score=score, classified_count=len(items), rationale=rationale)
        return {asset: result for asset in TRACKED_ASSETS}

    @staticmethod
    def _text_for(item: NewsItem) -> str:
        if item.summary:
            return f"{item.headline}. {item.summary}"
        return item.headline
