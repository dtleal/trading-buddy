"""Domain enumerations. Stable identifiers used across the application."""

from __future__ import annotations

from enum import Enum


class AssetSymbol(str, Enum):
    """Tradable assets the buddy tracks."""

    USTEC = "USTEC"  # Nasdaq 100 (Yahoo: ^NDX)
    SPX = "SPX"  # S&P 500 (Yahoo: ^GSPC)
    GOLD = "GOLD"  # Gold futures (Yahoo: GC=F)


class VolatilityIndex(str, Enum):
    """Volatility / fear gauges. Not traded but used as context."""

    VIX = "VIX"  # 30-day implied vol on SPX (^VIX)
    VIX9D = "VIX9D"  # 9-day implied vol (^VIX9D)
    VIX3M = "VIX3M"  # 3-month implied vol (^VIX3M)


class ImpactLevel(str, Enum):
    """Economic-event impact tier (matches ForexFactory taxonomy)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BiasLevel(str, Enum):
    """Discrete bias verdict derived from a 0-100 score."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class VixRegime(str, Enum):
    """VIX absolute-level regime band."""

    LOW = "low"  # < 15
    MID = "mid"  # 15 - 25
    HIGH = "high"  # > 25


class TermStructure(str, Enum):
    """VIX9D / VIX3M relationship — proxy for short-term stress."""

    CONTANGO = "contango"  # back > front; market calm
    BACKWARDATION = "backwardation"  # front > back; short-term stress
    FLAT = "flat"


class SentimentLabel(str, Enum):
    """News headline sentiment polarity."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class LLMOutputKind(str, Enum):
    """Categories of LLM-generated artefacts persisted in `llm_outputs`."""

    BRIEFING = "briefing"
    EVENT_PRE = "event_pre"
    EVENT_POST = "event_post"


class Timeframe(str, Enum):
    """Bar timeframes used by the breakout detector.

    Higher timeframes are computed by resampling the base 5m yfinance bars in
    memory — see `use_cases/resample_bars.py`. `M5` is here for completeness
    (the source bars) but the detector skips it on purpose; signals at 5m are
    too noisy and would flood the alert stream.
    """

    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "60m"
    H4 = "4h"


class BreakoutDirection(str, Enum):
    """Side of a Donchian breakout."""

    UP = "up"  # close > highest high of the last N bars
    DOWN = "down"  # close < lowest low of the last N bars
