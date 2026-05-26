"""Keyword-based sentiment classifier.

Default MVP `SentimentClassifier`. Zero dependencies, deterministic, and good
enough for noisy financial headlines. To swap in a real model later, drop in
another adapter implementing `core.interfaces.SentimentClassifier` (e.g.
HuggingFace `ProsusAI/finbert`) and rewire the container.
"""

from __future__ import annotations

import re

from core.enums import SentimentLabel

POSITIVE_TERMS: frozenset[str] = frozenset(
    {
        "beats",
        "beat",
        "exceeds",
        "surge",
        "surges",
        "rally",
        "rallies",
        "soars",
        "gains",
        "gained",
        "rises",
        "rose",
        "jump",
        "jumps",
        "record high",
        "all-time high",
        "upgrade",
        "upgraded",
        "bullish",
        "outperform",
        "strong",
        "growth",
        "expansion",
        "dovish",
        "cut",
        "easing",
        "stimulus",
        "optimism",
    }
)

NEGATIVE_TERMS: frozenset[str] = frozenset(
    {
        "miss",
        "missed",
        "misses",
        "slump",
        "slumps",
        "plunge",
        "plunges",
        "drops",
        "drop",
        "falls",
        "fell",
        "crash",
        "crashes",
        "tumble",
        "tumbles",
        "warns",
        "warning",
        "downgrade",
        "downgraded",
        "bearish",
        "underperform",
        "weak",
        "recession",
        "contraction",
        "hawkish",
        "hike",
        "tightening",
        "inflation",
        "uncertainty",
        "fears",
        "concerns",
        "sell-off",
        "selloff",
    }
)

_WORD_RE = re.compile(r"[A-Za-z\-']+")


class KeywordSentimentClassifier:
    """Implements `core.interfaces.SentimentClassifier`.

    The score is `(pos - neg) / (pos + neg + 1)`, clamped to [-1.0, 1.0].
    """

    async def classify(self, text: str) -> tuple[SentimentLabel, float]:
        lowered = text.lower()
        tokens = set(_WORD_RE.findall(lowered))

        # Multi-word matches (e.g. "all-time high") via substring check.
        positive_hits = sum(1 for term in POSITIVE_TERMS if term in lowered)
        negative_hits = sum(1 for term in NEGATIVE_TERMS if term in lowered)

        # Token-exact matches add precision over substring noise.
        positive_hits += sum(1 for term in POSITIVE_TERMS if term in tokens)
        negative_hits += sum(1 for term in NEGATIVE_TERMS if term in tokens)

        if positive_hits == 0 and negative_hits == 0:
            return SentimentLabel.NEUTRAL, 0.0

        score = (positive_hits - negative_hits) / (positive_hits + negative_hits + 1)
        score = max(-1.0, min(1.0, score))
        if score > 0.15:
            return SentimentLabel.POSITIVE, score
        if score < -0.15:
            return SentimentLabel.NEGATIVE, score
        return SentimentLabel.NEUTRAL, score
