"""Protocol interfaces (ports) that every adapter implements.

`core` does not import from `adapters` or `use_cases`. Adapters depend on
these Protocols; use cases depend on these Protocols. This is the seam that
keeps the domain free of I/O concerns.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from core.enums import (
    AssetSymbol,
    LLMOutputKind,
    SentimentLabel,
    VolatilityIndex,
)
from core.models import (
    BiasReport,
    EconomicEvent,
    FedWatchProbability,
    LLMOutput,
    MacroIndicator,
    MarketSnapshot,
    NewsItem,
    PriceQuote,
    QAEntry,
)

# -----------------------------------------------------------------------------
# Gateways (outbound — data we pull from the world)
# -----------------------------------------------------------------------------


@runtime_checkable
class PricesGateway(Protocol):
    async def get_quote(self, symbol: str) -> PriceQuote: ...

    async def get_ma200(self, symbol: str, interval: str) -> float | None: ...


@runtime_checkable
class CalendarGateway(Protocol):
    async def get_events_for(self, day: date) -> list[EconomicEvent]: ...


@runtime_checkable
class NewsGateway(Protocol):
    """A single news source. Multiple implementations are aggregated together."""

    source_name: str

    async def fetch_recent(self, limit: int = 50) -> list[NewsItem]: ...


@runtime_checkable
class MacroGateway(Protocol):
    async def get_indicator(self, series_id: str) -> MacroIndicator | None: ...

    async def get_fedwatch(self) -> FedWatchProbability | None: ...


# -----------------------------------------------------------------------------
# Inference
# -----------------------------------------------------------------------------


@runtime_checkable
class SentimentClassifier(Protocol):
    async def classify(self, text: str) -> tuple[SentimentLabel, float]:
        """Return (label, score in [-1.0, 1.0])."""
        ...


@runtime_checkable
class LLMGateway(Protocol):
    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        kind: LLMOutputKind,
        model: str | None = None,
        max_tokens: int = 1500,
    ) -> LLMOutput: ...


# -----------------------------------------------------------------------------
# Cache
# -----------------------------------------------------------------------------


@runtime_checkable
class CacheStore(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...


# -----------------------------------------------------------------------------
# Repositories (persistence)
# -----------------------------------------------------------------------------


@runtime_checkable
class SnapshotRepository(Protocol):
    async def save_market_snapshot(self, snapshot: MarketSnapshot) -> None: ...

    async def save_bias_reports(self, reports: list[BiasReport]) -> None: ...

    async def save_events(self, events: list[EconomicEvent]) -> None: ...

    async def save_news(self, items: list[NewsItem]) -> None: ...

    async def save_llm_output(self, output: LLMOutput) -> None: ...

    async def latest_briefing_for(self, day: date) -> LLMOutput | None: ...


@runtime_checkable
class QARepository(Protocol):
    """CRUD persistence for user-curated Q&A entries."""

    async def list_entries(self) -> list[QAEntry]:
        """Return every entry, most recently updated first."""
        ...

    async def get_entry(self, entry_id: int) -> QAEntry | None: ...

    async def create_entry(self, *, question: str, answer: str, tags: list[str]) -> QAEntry: ...

    async def update_entry(
        self, entry_id: int, *, question: str, answer: str, tags: list[str]
    ) -> QAEntry | None:
        """Update an entry by id. Returns None if no such entry exists."""
        ...

    async def delete_entry(self, entry_id: int) -> bool:
        """Delete an entry by id. Returns False if no such entry existed."""
        ...


__all__ = [
    "PricesGateway",
    "CalendarGateway",
    "NewsGateway",
    "MacroGateway",
    "SentimentClassifier",
    "LLMGateway",
    "CacheStore",
    "SnapshotRepository",
    "QARepository",
    "AssetSymbol",
    "VolatilityIndex",
]
