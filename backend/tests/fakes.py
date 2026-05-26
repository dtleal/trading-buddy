"""In-memory fakes that implement every Protocol in `core.interfaces`.

Tests inject these instead of hitting the network or a real database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

from day_trading_buddy.core.enums import LLMOutputKind, SentimentLabel
from day_trading_buddy.core.models import (
    BiasReport,
    EconomicEvent,
    FedWatchProbability,
    LLMOutput,
    MacroIndicator,
    MarketSnapshot,
    NewsItem,
    PriceQuote,
)

# -----------------------------------------------------------------------------
# Cache
# -----------------------------------------------------------------------------


class InMemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:  # noqa: ARG002
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


# -----------------------------------------------------------------------------
# Prices
# -----------------------------------------------------------------------------


@dataclass
class FakePricesGateway:
    quotes: dict[str, PriceQuote] = field(default_factory=dict)
    ma200_map: dict[tuple[str, str], float | None] = field(default_factory=dict)

    async def get_quote(self, symbol: str) -> PriceQuote:
        if symbol not in self.quotes:
            return PriceQuote(
                symbol=symbol,
                price=100.0,
                timestamp=datetime.now(timezone.utc),
            )
        return self.quotes[symbol]

    async def get_ma200(self, symbol: str, interval: str) -> float | None:
        return self.ma200_map.get((symbol, interval))


# -----------------------------------------------------------------------------
# Calendar / News / Macro
# -----------------------------------------------------------------------------


@dataclass
class FakeCalendarGateway:
    events_by_day: dict[date, list[EconomicEvent]] = field(default_factory=dict)

    async def get_events_for(self, day: date) -> list[EconomicEvent]:
        return list(self.events_by_day.get(day, []))


@dataclass
class FakeNewsGateway:
    source_name: str = "fake"
    items: list[NewsItem] = field(default_factory=list)

    async def fetch_recent(self, limit: int = 50) -> list[NewsItem]:  # noqa: ARG002
        return list(self.items)


@dataclass
class FakeMacroGateway:
    indicators: dict[str, MacroIndicator] = field(default_factory=dict)
    fedwatch: FedWatchProbability | None = None

    async def get_indicator(self, series_id: str) -> MacroIndicator | None:
        return self.indicators.get(series_id)

    async def get_fedwatch(self) -> FedWatchProbability | None:
        return self.fedwatch


# -----------------------------------------------------------------------------
# Sentiment / LLM
# -----------------------------------------------------------------------------


@dataclass
class FakeSentimentClassifier:
    rule: Callable[[str], tuple[SentimentLabel, float]] | None = None

    async def classify(self, text: str) -> tuple[SentimentLabel, float]:
        if self.rule is not None:
            return self.rule(text)
        return SentimentLabel.NEUTRAL, 0.0


@dataclass
class FakeLLMGateway:
    canned_response: str = "fake briefing"
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        kind: LLMOutputKind,
        model: str | None = None,
        max_tokens: int = 1500,
    ) -> LLMOutput:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "kind": kind,
                "model": model,
                "max_tokens": max_tokens,
            }
        )
        return LLMOutput(
            kind=kind,
            model=model or "fake-model",
            prompt_hash="fakehash",
            content=self.canned_response,
            created_at=datetime.now(timezone.utc),
        )


# -----------------------------------------------------------------------------
# Repository
# -----------------------------------------------------------------------------


@dataclass
class FakeSnapshotRepository:
    market_snapshots: list[MarketSnapshot] = field(default_factory=list)
    bias_reports: list[BiasReport] = field(default_factory=list)
    events: list[EconomicEvent] = field(default_factory=list)
    news: list[NewsItem] = field(default_factory=list)
    llm_outputs: list[LLMOutput] = field(default_factory=list)

    async def save_market_snapshot(self, snapshot: MarketSnapshot) -> None:
        self.market_snapshots.append(snapshot)

    async def save_bias_reports(self, reports: list[BiasReport]) -> None:
        self.bias_reports.extend(reports)

    async def save_events(self, events: list[EconomicEvent]) -> None:
        self.events.extend(events)

    async def save_news(self, items: list[NewsItem]) -> None:
        self.news.extend(items)

    async def save_llm_output(self, output: LLMOutput) -> None:
        self.llm_outputs.append(output)

    async def latest_briefing_for(self, day: date) -> LLMOutput | None:
        same_day = [
            o
            for o in self.llm_outputs
            if o.kind == LLMOutputKind.BRIEFING and o.created_at.date() == day
        ]
        return same_day[-1] if same_day else None
