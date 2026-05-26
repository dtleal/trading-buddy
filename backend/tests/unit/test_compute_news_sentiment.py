from __future__ import annotations

from datetime import datetime, timezone

import pytest

from day_trading_buddy.core.enums import AssetSymbol, SentimentLabel
from day_trading_buddy.core.models import NewsItem
from day_trading_buddy.use_cases.compute_news_sentiment import ComputeNewsSentimentUseCase
from tests.fakes import FakeSentimentClassifier


@pytest.mark.asyncio
async def test_empty_news_returns_neutral_for_all_assets() -> None:
    uc = ComputeNewsSentimentUseCase(FakeSentimentClassifier())
    result = await uc.execute([])
    for asset in AssetSymbol:
        assert result[asset].score == 50.0
        assert result[asset].classified_count == 0


@pytest.mark.asyncio
async def test_all_positive_news_pushes_score_up() -> None:
    classifier = FakeSentimentClassifier(rule=lambda _: (SentimentLabel.POSITIVE, 1.0))
    uc = ComputeNewsSentimentUseCase(classifier)
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            headline=f"good news {i}",
            source="fake",
            url=f"https://example.com/{i}",
            published_at=now,
        )
        for i in range(3)
    ]
    result = await uc.execute(items)
    for asset in AssetSymbol:
        assert result[asset].score > 90.0


@pytest.mark.asyncio
async def test_all_negative_news_pushes_score_down() -> None:
    classifier = FakeSentimentClassifier(rule=lambda _: (SentimentLabel.NEGATIVE, -1.0))
    uc = ComputeNewsSentimentUseCase(classifier)
    now = datetime.now(timezone.utc)
    items = [
        NewsItem(
            headline=f"bad news {i}",
            source="fake",
            url=f"https://example.com/{i}",
            published_at=now,
        )
        for i in range(3)
    ]
    result = await uc.execute(items)
    for asset in AssetSymbol:
        assert result[asset].score < 10.0
