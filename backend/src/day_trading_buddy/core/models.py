"""Domain models. Frozen Pydantic DTOs that flow across layers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from day_trading_buddy.core.enums import (
    AssetSymbol,
    BiasLevel,
    ImpactLevel,
    LLMOutputKind,
    SentimentLabel,
    TermStructure,
    VixRegime,
    VolatilityIndex,
)


class _Frozen(BaseModel):
    """Base for immutable DTOs."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# -----------------------------------------------------------------------------
# Market data
# -----------------------------------------------------------------------------


class PriceQuote(_Frozen):
    """Single point-in-time quote for an asset or volatility index."""

    symbol: str
    price: float
    timestamp: datetime
    ma200_d: float | None = None  # Daily 200-period SMA
    ma200_h4: float | None = None  # 4-hour 200-period SMA
    change_pct: float | None = None  # Day change %


class VixSnapshot(_Frozen):
    """VIX complex view used to classify regime and term structure."""

    vix: float
    vix9d: float | None
    vix3m: float | None
    regime: VixRegime
    term_structure: TermStructure


class MarketSnapshot(_Frozen):
    """All asset + vol quotes for a single 5-minute tick."""

    timestamp: datetime
    assets: dict[AssetSymbol, PriceQuote]
    vix: VixSnapshot


# -----------------------------------------------------------------------------
# Economic calendar
# -----------------------------------------------------------------------------


class EconomicEvent(_Frozen):
    """A scheduled or just-released macro release."""

    name: str  # e.g. "CPI YoY", "FOMC Statement"
    currency: str  # e.g. "USD"
    impact: ImpactLevel
    scheduled_at: datetime  # UTC
    forecast: str | None = None
    previous: str | None = None
    actual: str | None = None  # Populated after release
    source: str = "forexfactory"


# -----------------------------------------------------------------------------
# News
# -----------------------------------------------------------------------------


class NewsItem(_Frozen):
    """A single news headline with optional sentiment metadata."""

    headline: str
    source: str
    url: str
    published_at: datetime
    summary: str | None = None
    sentiment_label: SentimentLabel | None = None
    sentiment_score: float | None = None  # [-1.0, 1.0]


# -----------------------------------------------------------------------------
# Macro indicators
# -----------------------------------------------------------------------------


class MacroIndicator(_Frozen):
    """A single macro reading (FRED-style)."""

    series_id: str  # e.g. "DFF" (Fed funds), "DGS10" (10Y yield), "DTWEXBGS" (DXY proxy)
    value: float
    observed_at: datetime
    delta_1d: float | None = None
    delta_1w: float | None = None


class FedWatchProbability(_Frozen):
    """CME FedWatch implied probability for next FOMC meeting."""

    meeting_date: datetime
    cut_50: float = 0.0
    cut_25: float = 0.0
    hold: float = 0.0
    hike_25: float = 0.0
    hike_50: float = 0.0


class MacroSnapshot(_Frozen):
    """Aggregate of macro indicators and FedWatch state."""

    timestamp: datetime
    indicators: dict[str, MacroIndicator]
    fedwatch: FedWatchProbability | None = None


# -----------------------------------------------------------------------------
# Bias
# -----------------------------------------------------------------------------


class BiasComponents(_Frozen):
    """Sub-scores feeding the combined bias for a single asset."""

    technical: float  # 0-100
    macro: float  # 0-100
    sentiment: float  # 0-100


class BiasReport(_Frozen):
    """Per-asset, per-tick bias verdict."""

    asset: AssetSymbol
    timestamp: datetime
    score: float = Field(ge=0.0, le=100.0)
    level: BiasLevel
    components: BiasComponents
    rationale: list[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# LLM outputs
# -----------------------------------------------------------------------------


class LLMOutput(_Frozen):
    """Persisted Claude response. Keyed by content hash for idempotency."""

    kind: LLMOutputKind
    model: str
    prompt_hash: str
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


# -----------------------------------------------------------------------------
# Tick aggregate
# -----------------------------------------------------------------------------


class DashboardTick(_Frozen):
    """Everything one 5-minute tick produces; consumed by the dashboard renderer."""

    timestamp: datetime
    market: MarketSnapshot
    macro: MacroSnapshot
    events_today: list[EconomicEvent]
    recent_news: list[NewsItem]
    bias: dict[AssetSymbol, BiasReport]


__all__ = [
    "PriceQuote",
    "VixSnapshot",
    "MarketSnapshot",
    "EconomicEvent",
    "NewsItem",
    "MacroIndicator",
    "FedWatchProbability",
    "MacroSnapshot",
    "BiasComponents",
    "BiasReport",
    "LLMOutput",
    "DashboardTick",
    "VolatilityIndex",
]
