"""Domain models. Frozen Pydantic DTOs that flow across layers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AssetSymbol,
    BiasLevel,
    BreakoutDirection,
    ImpactLevel,
    LLMOutputKind,
    SentimentLabel,
    TermStructure,
    Timeframe,
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
# Intraday price action (5m timeframe — used by `dtb signal`)
# -----------------------------------------------------------------------------


class IntradayBar(_Frozen):
    """One OHLCV bar at the configured intraday interval (default 5m)."""

    timestamp: datetime  # bar open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float


class IntradayLevels(_Frozen):
    """Deterministic price-action levels computed from intraday bars.

    All prices are in the same units as the underlying ticker (index points
    for ^NDX/^GSPC, dollars for GC=F). No directional opinion — the consumer
    decides the trade. Stop candidates are reported as price levels (last swing
    high/low ± optional buffer); position sizing helpers live in the CLI layer.
    """

    symbol: str
    asof: datetime  # bar timestamp of the latest bar consumed
    last_price: float

    # Session extremes
    hod: float  # high of day so far
    lod: float  # low of day so far

    # Volume-weighted average price (intraday, cumulative)
    vwap: float | None

    # Opening range (configurable window; default = first 30 min of US session)
    orh: float | None
    orl: float | None

    # Previous-day reference levels
    pdc: float | None  # previous day close
    pdh: float | None  # previous day high
    pdl: float | None  # previous day low

    # Short-term EMAs on the bar timeframe (e.g. 5m)
    ema_9: float | None
    ema_20: float | None
    ema_50: float | None

    # Long-term means on the bar timeframe (e.g. 5m). Require 200+ bars.
    ema_200: float | None
    sma_200: float | None

    # Average True Range (14 bars) on the bar timeframe
    atr_14: float | None

    # Last 3-bar swing pivots within the session
    last_swing_high: float | None
    last_swing_high_at: datetime | None
    last_swing_low: float | None
    last_swing_low_at: datetime | None


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
# Trade setups (only emitted when objective confluence is detected)
# -----------------------------------------------------------------------------


class IntradayBiasReport(_Frozen):
    """Per-asset, per-tick **intraday** verdict derived from the 5m structure.

    This is the COMPANION to BiasReport, which encodes the daily structural
    view. A 5m trader cares about both: BiasReport tells them the macro
    backdrop; IntradayBiasReport tells them what the tape is doing right now.

    Score range is 0-100 anchored at 50 (neutral). Each rule adjusts the
    score up/down; the `signals` list explains the contributing factors so
    the frontend can render a readable tooltip.
    """

    asset: AssetSymbol
    score: float = Field(ge=0.0, le=100.0)
    level: BiasLevel
    signals: list[str] = Field(default_factory=list)


class Breakout(_Frozen):
    """A Donchian-channel breakout detected on one asset / one timeframe.

    `id` is stable for the same breakout event across ticks: keyed by
    (asset, timeframe, direction, signal_bar_timestamp). The frontend uses it
    to dedup alerts when the same recent breakout shows up in successive ticks.
    """

    id: str
    asset: AssetSymbol
    timeframe: Timeframe
    direction: BreakoutDirection

    # The level that got broken (highest-high or lowest-low of the prior N bars).
    level: float
    # Close of the signal bar (the one that broke through).
    close: float
    # Range of the signal bar in price units.
    bar_range: float
    # Expansion ratio = bar_range / ATR(14). > 1.3 by detector design.
    expansion_ratio: float
    # Composite strength (0-100). Combines expansion + how far past `level`.
    strength: float
    # Was the volatility contracting *before* the break? (ATR(14) < SMA20 of ATR.)
    squeeze: bool

    # Timestamp of the signal bar (UTC, ISO 8601 when serialized).
    signal_bar_at: datetime
    # When the detector first emitted this event.
    detected_at: datetime


class TradeSetup(_Frozen):
    """A high-confluence trade idea detected by `DetectTradeSetupUseCase`.

    This is a *heuristic* — multiple data conditions aligning in a way the
    literature considers favorable. It is NOT a forecast. The user always
    decides whether to take the trade.
    """

    asset: AssetSymbol
    direction: Literal["LONG", "SHORT"]
    trend_label: str  # e.g. "tendência alta forte"
    continuation_label: str  # e.g. "alta probabilidade de continuação"
    entry_zone_low: float
    entry_zone_high: float
    stop_level: float
    target_level: float
    risk_reward: float
    rationale: list[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Q&A knowledge base (user-curated playbook entries)
# -----------------------------------------------------------------------------


class QAEntry(_Frozen):
    """A saved question/answer pair the user keeps as a day-to-day reference.

    The answer is stored as markdown so the frontend can render formatting
    (headings, lists, bold) the same way the briefing panel does. `tags` are
    free-form, normalised (lowercased, de-duped) labels used for filtering.
    """

    id: int
    question: str
    answer: str  # markdown
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


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
# Order flow (live DOM / footprint / tape — fed by the MT5 collector)
# -----------------------------------------------------------------------------
#
# This layer is NOT produced by the 5m tick loop. It is pushed in real time by
# an external collector (see `collector/`) that runs next to a MetaTrader 5
# terminal on Windows, reads the broker's depth-of-market + trade ticks, and
# streams them to the backend ingest WebSocket. The backend aggregates the raw
# stream into the three flow-trader views below and fans them out to browsers
# over `/ws/orderflow`. Only USTEC / SPX / GOLD carry order flow (no BITCOIN).


TradeSide = Literal["buy", "sell", "unknown"]


class OrderBookLevel(_Frozen):
    """A single price rung in the depth-of-market ladder."""

    price: float
    volume: float  # resting size at this price (broker units / lots)


class OrderBookSnapshot(_Frozen):
    """Top-N depth of market for one symbol at a point in time.

    `bids` are sorted best (highest price) first; `asks` best (lowest price)
    first. Sizes are resting limit liquidity — NOT executed volume.
    """

    symbol: AssetSymbol
    asof: datetime
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)


class TapeTrade(_Frozen):
    """A single executed trade on the time & sales tape.

    `side` is the aggressor: `buy` = lifted the ask, `sell` = hit the bid.
    For CFD feeds that don't tag aggressor, the collector falls back to
    comparing last vs bid/ask, and may emit `unknown`.
    """

    symbol: AssetSymbol
    at: datetime
    price: float
    volume: float
    side: TradeSide


class FootprintCell(_Frozen):
    """Executed volume at one price within a footprint bar, split by aggressor.

    `delta` (ask_volume - bid_volume) is computed by the frontend; we keep the
    raw split here so the client can render bid×ask and color the imbalance.
    """

    price: float
    bid_volume: float  # volume that hit the bid (sell aggressor)
    ask_volume: float  # volume that lifted the ask (buy aggressor)


class FootprintBar(_Frozen):
    """One time-bucketed footprint bar: per-price aggressor split + totals."""

    symbol: AssetSymbol
    bar_open: datetime  # bucket start (UTC), aligned to interval_seconds
    interval_seconds: int
    cells: list[FootprintCell] = Field(default_factory=list)  # sorted high→low price
    bid_volume: float = 0.0  # bar total hitting the bid
    ask_volume: float = 0.0  # bar total lifting the ask
    delta: float = 0.0  # ask_volume - bid_volume
    poc_price: float | None = None  # point of control (max total-volume price)


class OrderFlowSnapshot(_Frozen):
    """Per-symbol order-flow state broadcast to the frontend.

    One message per symbol. The book is the latest DOM; `recent_trades` is the
    tail of the tape (newest last); `footprint` is the last few completed +
    in-progress bars (newest last).
    """

    symbol: AssetSymbol
    asof: datetime
    book: OrderBookSnapshot | None = None
    recent_trades: list[TapeTrade] = Field(default_factory=list)
    footprint: list[FootprintBar] = Field(default_factory=list)


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
    setups: list[TradeSetup] = Field(default_factory=list)
    intraday_levels: dict[AssetSymbol, "IntradayLevels"] = Field(default_factory=dict)
    intraday_bias: dict[AssetSymbol, IntradayBiasReport] = Field(default_factory=dict)
    breakouts_recent: list[Breakout] = Field(default_factory=list)


__all__ = [
    "PriceQuote",
    "VixSnapshot",
    "MarketSnapshot",
    "IntradayBar",
    "IntradayLevels",
    "EconomicEvent",
    "NewsItem",
    "MacroIndicator",
    "FedWatchProbability",
    "MacroSnapshot",
    "BiasComponents",
    "BiasReport",
    "IntradayBiasReport",
    "TradeSetup",
    "Breakout",
    "QAEntry",
    "LLMOutput",
    "DashboardTick",
    "VolatilityIndex",
    "TradeSide",
    "OrderBookLevel",
    "OrderBookSnapshot",
    "TapeTrade",
    "FootprintCell",
    "FootprintBar",
    "OrderFlowSnapshot",
]
