from __future__ import annotations

import pytest

from adapters.sentiment_keyword import KeywordSentimentClassifier
from core.enums import SentimentLabel


@pytest.mark.asyncio
async def test_positive_headline_is_positive() -> None:
    label, score = await KeywordSentimentClassifier().classify(
        "Nvidia beats earnings, guidance strong"
    )
    assert label == SentimentLabel.POSITIVE
    assert score > 0.0


@pytest.mark.asyncio
async def test_negative_headline_is_negative() -> None:
    label, score = await KeywordSentimentClassifier().classify(
        "Stocks plunge as Fed warns of further rate hikes"
    )
    assert label == SentimentLabel.NEGATIVE
    assert score < 0.0


@pytest.mark.asyncio
async def test_neutral_headline_is_neutral() -> None:
    label, score = await KeywordSentimentClassifier().classify(
        "Apple announces new product launch event"
    )
    assert label == SentimentLabel.NEUTRAL
    assert -0.15 <= score <= 0.15
