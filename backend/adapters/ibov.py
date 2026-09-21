"""Ibovespa weights, and how much each heavy name is pushing the index today.

Two sources, on purpose:

- The weights are B3's own theoretical portfolio, saved to `data/ibov_pesos.json`.
  B3 rebalances it three times a year, so fetching it live would be ten
  requests a minute for a number that moves in January, May and September.
- The day's move comes from Yahoo, delayed ~15 minutes. That is fine for what
  this answers — which names are carrying the index — because the number that
  matters is weight × move, not the tick.

One download call covers every ticker, which is why the codes are fetched
together instead of one by one.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import yfinance as yf

logger = logging.getLogger(__name__)

# Beside the code on purpose: `data/` is gitignored (it is where the recorded
# tapes land), and a clone without this file would draw an empty panel.
WEIGHTS_PATH = Path(__file__).resolve().parent / "ibov_pesos.json"


@dataclass(frozen=True, slots=True)
class IbovStock:
    cod: str
    nome: str
    peso: float  # share of the index, in percent


def load_weights(top: int | None = None) -> tuple[str, list[IbovStock]]:
    """The heaviest names first, plus the date of the B3 portfolio they come
    from. `top` cuts the list; None is the whole index. Empty when the file is
    missing, so the panel says so instead of inventing an index."""
    try:
        raw = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("ibov: nao consegui ler %s", WEIGHTS_PATH)
        return "", []
    stocks = [
        IbovStock(cod=item["cod"], nome=item["nome"], peso=float(item["peso"]))
        for item in raw.get("acoes", [])[:top]
    ]
    return str(raw.get("data", "")), stocks


def fetch_changes(codes: list[str]) -> dict[str, float]:
    """Today's move per code, in percent. Codes Yahoo does not answer for are
    left out rather than reported as zero — a missing quote is not a flat day."""
    if not codes:
        return {}
    tickers = [f"{code}.SA" for code in codes]
    try:
        data = yf.download(
            tickers, period="5d", interval="1d", progress=False,
            group_by="ticker", auto_adjust=False, threads=True,
        )
    except Exception:
        logger.exception("ibov: falha buscando cotacao no Yahoo")
        return {}
    changes: dict[str, float] = {}
    for code, ticker in zip(codes, tickers):
        try:
            closes = data[ticker]["Close"].dropna()
        except (KeyError, TypeError):
            continue
        if len(closes) < 2 or not closes.iloc[-2]:
            continue
        changes[code] = float(closes.iloc[-1] / closes.iloc[-2] - 1.0) * 100.0
    return changes
