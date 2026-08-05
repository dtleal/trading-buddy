"""Domain enumerations. Stable identifiers used across the application."""

from __future__ import annotations

from enum import Enum


class AssetSymbol(str, Enum):
    """Tradable assets the buddy tracks.

    `BITCOIN` is kept here on purpose even though nothing tracks it any more:
    snapshots saved before it was dropped still carry the string, so removing
    the member would make those old rows fail to parse. The live asset list is
    `TRACKED_ASSETS` below — that is what the dashboard reads.
    """

    USTEC = "USTEC"  # Nasdaq 100 (Yahoo: ^NDX / NQ=F intraday)
    SPX = "SPX"  # S&P 500 (Yahoo: ^GSPC / ES=F intraday)
    GOLD = "GOLD"  # Gold futures (Yahoo: GC=F)
    US30 = "US30"  # Dow Jones 30 (Yahoo: ^DJI / YM=F intraday)
    USOIL = "USOIL"  # WTI crude oil (Yahoo: CL=F)
    US2000 = "US2000"  # Russell 2000 (Yahoo: ^RUT / RTY=F intraday)
    BITCOIN = "BITCOIN"  # retired — see the class docstring


"""The assets the dashboard tracks, in display order.

Every per-asset loop must walk this tuple rather than `AssetSymbol` itself,
otherwise the retired `BITCOIN` member reappears in the output with empty
scores. Bitcoin was dropped to make screen room for the three FTMO instruments
the trader actually works (US30.cash / USOIL.cash / US2000.cash)."""
TRACKED_ASSETS: tuple[AssetSymbol, ...] = (
    AssetSymbol.USTEC,
    AssetSymbol.SPX,
    AssetSymbol.GOLD,
    AssetSymbol.US30,
    AssetSymbol.USOIL,
    AssetSymbol.US2000,
)

"""Assets that fall when fear rises. The stock indices are the obvious ones;
oil belongs here too because a fear spike is read as a demand hit. Everything
outside this set is treated as risk-off (gold catches a bid when stress rises),
so the bias use cases only have to agree on this one list."""
RISK_ON_ASSETS: frozenset[AssetSymbol] = frozenset(
    {
        AssetSymbol.USTEC,
        AssetSymbol.SPX,
        AssetSymbol.US30,
        AssetSymbol.US2000,
        AssetSymbol.USOIL,
    }
)


class VolatilityIndex(str, Enum):
    """Volatility / fear gauges. Not traded but used as context."""

    VIX = "VIX"  # 30-day implied vol on SPX (^VIX)
    VIX9D = "VIX9D"  # 9-day implied vol (^VIX9D)
    VIX3M = "VIX3M"  # 3-month implied vol (^VIX3M)


class ImpactLevel(str, Enum):
    """Economic-event impact tier (matches ForexFactory taxonomy).

    `HOLIDAY` is a distinct tier (not a low-impact release): a bank holiday in
    the event's currency means the underlying cash market is closed or on a
    half-day, so index/gold CFD liquidity craters. The day-outlook assessor
    treats it as the strongest "thin session" signal, so we must NOT squash it
    into LOW the way the feed's own taxonomy implies.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    HOLIDAY = "holiday"


class DayRegime(str, Enum):
    """How much movement the session is expected to offer.

    Derived by `AssessDayOutlookUseCase` from a 0-100 movement-potential score.
    The trader uses it as a go/no-go gate: `THIN` days (holiday, no catalyst,
    collapsing volume) are the chop sessions where offsetting candles eat
    accounts; `EXPANSION` days carry a catalyst and live participation.
    """

    EXPANSION = "expansion"  # high movement potential — catalyst + liquidity
    NORMAL = "normal"  # ordinary session
    THIN = "thin"  # low participation / chop risk — trade small or stay out


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
