"""Domain models. Frozen Pydantic DTOs that flow across layers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.enums import (
    AssetSymbol,
    BiasLevel,
    BreakoutDirection,
    DayRegime,
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


class SessionLiquidity(_Frozen):
    """Today's realized participation vs the same-time-of-day baseline.

    Pushed by the MT5 collector (`type:"liquidity"`), which reads historical
    OHLCV via `copy_rates_*` and compares today's cumulative *tick volume* up
    to the current time of day against the median of the trailing N sessions at
    the same point in their day. `ratio` < 1 means the session is running
    thinner than usual — the empirical core of the thin/chop warning. Tick
    volume (count of price changes) is the only "volume" CFD feeds expose, but
    its *shape over the day* is a stable participation proxy.
    """

    symbol: AssetSymbol
    asof: datetime
    realized_volume: float  # cumulative tick volume so far today
    baseline_volume: float  # median cumulative tick volume at same time-of-day
    ratio: float  # volume realized / baseline (1.0 = normal participation)
    sample_days: int  # how many past sessions fed the baseline
    # Session travel (max high − min low so far) vs same-time-of-day baseline.
    # The "candles minúsculos, preço não anda" signal. Optional — present only
    # when the collector had enough history to compute a range baseline.
    realized_range: float | None = None
    baseline_range: float | None = None
    range_ratio: float | None = None  # range realized / baseline


class LiveActivity(_Frozen):
    """Real-time activity read derived from the live footprint the backend
    already receives — NO historical baseline needed, so it fills the instant
    flow arrives (unlike `SessionLiquidity`, which waits on the collector's
    `copy_rates` baseline). It answers "how big are the candles and how much is
    trading *right now*", which is the immediate read of the "preço não anda"
    feeling. The `SessionLiquidity` ratio, when present, layers the "vs normal"
    judgement on top.
    """

    range_per_bar: float  # median high−low of recent completed bars (price units)
    volume_per_bar: float  # median total volume of recent completed bars
    interval_seconds: int  # bar width, so the UI can normalise to per-minute
    sampled_bars: int  # completed bars that fed the medians


class Position(_Frozen):
    """One open MT5 position for a symbol, read live by the collector.

    Read-only mirror of `mt5.positions_get()` — the collector never places or
    modifies orders. `profit` is in the account currency. `seconds_open` is the
    time-in-trade computed on the collector at read time: MT5 reports the open
    time in the *broker's server clock* (not UTC), so we cannot subtract it from
    a browser/backend clock without skew — the collector does the subtraction
    against the broker clock and ships the result, which the UI ticks up locally.
    """

    symbol: AssetSymbol
    ticket: int  # broker position id (stable for the life of the position)
    side: Literal["buy", "sell"]  # buy = long, sell = short
    volume: float  # lots
    price_open: float
    price_current: float
    profit: float  # floating P&L in account currency
    sl: float | None = None  # stop loss price (None / 0 → not set)
    tp: float | None = None  # take profit price
    seconds_open: float  # time-in-trade at read time (broker-clock delta)


class TradeSignal(_Frozen):
    """A deterministic, in-trade alert about one open position.

    Computed live on each snapshot from the order flow + the position — NO LLM
    (a model round-trip is far too slow for a scalp that lasts seconds). It is
    decision support, not advice, and inherits the uncertainty of the flow it
    reads (synthesized tick-direction on CFD feeds, not real volume).

    - `code` identifies the rule. `severity` drives the UI emphasis. `stance` is
      the signal's relation to the position (against it / take-profit caution).
    - `ticket` ties the signal to its position so the UI can place it.
    """

    symbol: AssetSymbol
    ticket: int
    code: Literal["pressure_against", "take_profit"]
    severity: Literal["info", "warn", "urgent"]
    stance: Literal["against", "caution", "favor"]
    message: str


FlowSignalAction = Literal["enter_long", "enter_short", "exit", "hold"]
FlowSignalBasis = Literal["explosion", "lean", "reversal", "against", "exhaustion", "none"]


class FlowSignal(_Frozen):
    """THE per-symbol entry/exit signal derived from the live order flow.

    One signal per symbol per snapshot, computed by
    `use_cases.trade_signal.compute_flow_signal` from the exact same tape
    window / thresholds the scalper bot uses (`use_cases.scalper`) plus the
    in-trade against/stall rules (`use_cases.assess_trade_signals`). It is the
    single source of truth: the UI renders it as decision support for manual
    trading, and the armed bot consumes the SAME object for its enter/reverse
    decisions — the signal shown is the signal acted on.

    - `action` — what the flow says to do right now (relative to the open
      position, if any). `exit` only appears while holding.
    - `basis` — which flow evidence produced it: `explosion` (burst entry),
      `lean` (continuation lean while holding), `reversal` (flow flipped hard
      against the held side — the bot's stop-and-reverse), `against` (softer
      contrary pressure, advisory only), `exhaustion` (in profit + momentum
      stalled, advisory only), `none` (no judgement).
    - `strength` — 0..1 conviction cue for the UI; it is NOT an execution
      threshold (the bot keys off action+basis only).

    Like every flow read here, on quote-only CFD feeds this derives from a
    synthesized tape (tick direction, not real volume) — decision support,
    never advice.
    """

    symbol: AssetSymbol
    action: FlowSignalAction
    reason: str  # short PT human text for the UI
    strength: float = Field(ge=0.0, le=1.0)
    basis: FlowSignalBasis


class AutoCloseStatus(_Frozen):
    """State of the whole-account profit-target auto-close.

    `enabled` is the collector's capability (its `allow_auto_close` flag, learned
    from the `hello` message) — the UI can't arm execution unless the local
    collector also permits it. `armed` + `target_usd` are set from the UI.
    `open_profit` is the current summed floating P&L across all open positions,
    so the UI shows progress toward the target. After a fire the rule disarms
    itself (one-shot) and records `last_result` / `last_fired_at`.
    """

    enabled: bool = False
    armed: bool = False
    target_usd: float | None = None
    open_profit: float = 0.0
    last_fired_at: datetime | None = None
    last_result: str | None = None


class BotStatus(_Frozen):
    """State of the explosion-scalper bot (opens AND closes, demo only).

    `enabled` is the collector's capability — it requires the collector's
    `allow_auto_trade` flag AND a DEMO account; the UI can't arm otherwise.
    `armed` runs the bot. It opens on bursts up to a per-symbol cap and exits
    the whole account at `profit_target` (+) / `loss_stop` (−), disarming itself.
    """

    enabled: bool = False
    armed: bool = False
    profit_target: float = 350.0
    loss_stop: float = 900.0
    open_profit: float = 0.0  # current floating P&L (open positions)
    realized: float = 0.0  # banked P&L this session (sum of closed cycles)
    open_count: int = 0
    last_result: str | None = None


class BotTrade(_Frozen):
    """One persisted scalper-bot execution event (open or close). Read model for
    the trade-history endpoint; only bot trades are ever recorded."""

    id: int
    kind: Literal["open", "close"]
    symbol: str
    side: str | None = None
    lots: float | None = None
    ticket: int | None = None
    price: float | None = None
    pnl: float | None = None
    reason: str | None = None
    created_at: datetime


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
    # Which broker terminal is feeding this symbol's flow (FTMO, ActivTrades,
    # …). Set by the collector via a `hello` message on connect; carried on
    # every snapshot so the UI can label each column.
    source: str | None = None
    # MT5 login number of the account feeding this flow. Set by the collector via
    # the same `hello` message as `source`; carried on every snapshot so the UI
    # can show exactly which account is connected next to the broker name.
    account: int | None = None
    # Latest session-liquidity reading for this symbol (today's tick volume vs
    # the same-time-of-day baseline). Stamped onto every broadcast so each flow
    # column can show "X% do volume normal" right above its pressure bar.
    liquidity: SessionLiquidity | None = None
    # Real-time candle-size + volume read from the live footprint. Always present
    # once any bar exists (no baseline needed), so the UI shows activity the
    # instant flow arrives.
    live_activity: LiveActivity | None = None
    # Open positions for this symbol, read live from MT5 by the collector. Empty
    # when flat. Stamped onto every broadcast so the UI can overlay live P&L and
    # time-in-trade next to the flow.
    positions: list[Position] = Field(default_factory=list)
    # Deterministic in-trade alerts about the open positions (pressure turning
    # against you, profit + momentum stalling). Recomputed on every broadcast.
    signals: list[TradeSignal] = Field(default_factory=list)
    # THE single per-symbol entry/exit signal derived from the flow (see
    # FlowSignal). Stamped on every broadcast; the armed bot follows the same
    # object, so what the UI shows is exactly what the bot acts on.
    flow_signal: FlowSignal | None = None


# -----------------------------------------------------------------------------
# Day outlook (movement-potential / liquidity gate)
# -----------------------------------------------------------------------------


class DayOutlook(_Frozen):
    """Whether the session promises real movement or is a thin/chop trap.

    Produced once per tick by `AssessDayOutlookUseCase` by combining structural
    signals known at/near the open (bank holiday, scheduled high-impact
    catalysts, VIX regime, opening-range compression vs ATR) with the live MT5
    tick-volume `ratio` when a collector is feeding it. `score` is 0-100
    movement potential anchored at 50; `regime` is the discrete go/no-go gate;
    `rationale` explains the drivers for the dashboard tooltip and the push.
    """

    asof: datetime
    score: float = Field(ge=0.0, le=100.0)
    regime: DayRegime
    headline: str  # one-line PT verdict for the banner / push title
    rationale: list[str] = Field(default_factory=list)
    is_us_holiday: bool = False
    high_impact_count: int = 0  # scheduled HIGH-impact USD events today
    liquidity_ratio: float | None = None  # blended MT5 ratio across symbols, if any


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
    day_outlook: DayOutlook | None = None


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
    "SessionLiquidity",
    "LiveActivity",
    "FlowSignal",
    "FlowSignalAction",
    "FlowSignalBasis",
    "DayOutlook",
]
