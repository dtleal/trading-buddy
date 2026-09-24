"""Jev trader: every 30s, per symbol. The Jev picks the entry (buy, sell or
wait); the exit is a fixed rule measured in ATR of the 5-minute candles.

Why the exit is not the Jev's call any more (replay of 23/09/2026): with the
Jev deciding exits, 164 trades lost $72 — trades lasted about a minute and the
spread ate almost everything. The same entries with a 1 ATR stop and a 1 ATR
trail made money. So:

- at most one new entry per symbol every ENTRY_SPACING_S;
- stop at STOP_ATR from the entry;
- one more lot each PYRAMID_ATR in our favour, up to MAX_ENTRIES;
- with more than one lot, close everything when price comes back TRAIL_ATR
  from the best price seen.

GOLD also trades mean reversion on the Bollinger bands when the market is flat
(`mean_reversion_signal`), the only symbol where it was positive in a 5-day
replay. Demo account only.
"""

from __future__ import annotations

import statistics
from typing import Any, Literal

ENTRY_MIN = 0.28  # Jev confidence needed to open
ENTRY_GAP = 0.1  # how much the chosen side must beat the other side
ENTRY_SPACING_S = 900  # at most one new entry per symbol in this window
STOP_ATR = 1.0
MAX_ENTRIES = 5  # most lots stacked on one symbol (first entry + adds)
PYRAMID_ATR = 1.0
TRAIL_ATR = 1.0

# Mean reversion (GOLD, flat market). Best consistent variant of the 5-day
# replay: the 20-period middle band moved less than MR_FLAT_ATR in 30 min, a 5m
# candle poked outside the band and closed back in, on the matching half of the
# 15m bands. Target: the other 5m band. Stop MR_STOP_ATR, give up after
# MR_MAX_S.
MR_SYMBOLS = frozenset({"GOLD"})
MR_FLAT_ATR = 0.2
MR_STOP_ATR = 2.0
MR_MAX_S = 2 * 3600

Action = Literal["buy", "sell", "wait"]


def entry_questions(symbol: str, price: float) -> dict[str, Any]:
    def side(verb: str, up: bool) -> dict[str, Any]:
        good = "alta (minimas subindo, acima do VWAP)" if up else "baixa (maximas caindo, abaixo do VWAP)"
        return {
            "type": "noul",
            "instructions": (
                f"Vale {verb} {symbol} agora em {price:.2f}? Pode ser um scalp ou um trade mais longo, "
                "o que os dados sustentarem. So diga sim com alta chance de o preco andar a favor."
            ),
            "criteria": {
                "true": f"estrutura de {good} e fluxo do mesmo lado, com espaco claro para andar",
                "false": "estrutura ou fluxo contra, sinais misturados, mercado lateral, ou o movimento ja aconteceu",
            },
        }

    return {"comprar": side("comprar", True), "vender": side("vender", False)}


def decide(answers: dict[str, float]) -> Action:
    buy, sell = answers.get("comprar", 0.0), answers.get("vender", 0.0)
    if max(buy, sell) < ENTRY_MIN or abs(buy - sell) < ENTRY_GAP:
        return "wait"
    return "buy" if buy > sell else "sell"


def atr(bars: list[Any]) -> float:
    """Mean high-low of the last 14 five-minute candles."""
    last = bars[-14:]
    return sum(b.high - b.low for b in last) / len(last)


def bollinger(closes: list[float], n: int = 20, k: float = 2.0) -> tuple[float, float, float] | None:
    if len(closes) < n:
        return None
    window = closes[-n:]
    mid, sd = statistics.mean(window), statistics.pstdev(window)
    return mid - k * sd, mid, mid + k * sd


def mean_reversion_signal(bars: list[Any]) -> Action:
    """Buy/sell on a band poke in a flat market, read on CLOSED 5m candles."""
    if len(bars) < 90:
        return "wait"
    closes = [b.close for b in bars]
    now, before = bollinger(closes), bollinger(closes[:-6])
    fifteen = bollinger(closes[2::3][-40:])  # every 3rd close: the 15m closes
    if now is None or before is None or fifteen is None:
        return "wait"
    if abs(now[1] - before[1]) > MR_FLAT_ATR * atr(bars):
        return "wait"  # the middle band is moving: not a flat market
    last = bars[-1]
    if last.low <= now[0] < last.close and last.close <= fifteen[1]:
        return "buy"
    if last.high >= now[2] > last.close and last.close >= fifteen[1]:
        return "sell"
    return "wait"


def band_target(bars: list[Any], side: str) -> float | None:
    """The other 5m band: where a mean-reversion trade takes its profit."""
    bands = bollinger([b.close for b in bars])
    if bands is None:
        return None
    return bands[2] if side == "buy" else bands[0]
