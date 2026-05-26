"""User-facing string table. The codebase is English; this is where output
text gets localised so the dashboard can render in Portuguese.
"""

from __future__ import annotations

from typing import Literal

Language = Literal["pt", "en"]

STRINGS: dict[str, dict[Language, str]] = {
    "title": {"pt": "DAY TRADING BUDDY", "en": "DAY TRADING BUDDY"},
    "prices_header": {"pt": "Preços", "en": "Prices"},
    "events_header": {"pt": "Eventos de hoje (US Eastern)", "en": "Today's events (US Eastern)"},
    "bias_header": {"pt": "Viés por ativo", "en": "Bias per asset"},
    "news_header": {"pt": "Manchetes recentes", "en": "Recent headlines"},
    "vix_header": {"pt": "VIX", "en": "VIX"},
    "macro_header": {"pt": "Macro", "en": "Macro"},
    "no_data": {"pt": "(sem dados)", "en": "(no data)"},
    "no_events": {"pt": "Sem eventos relevantes hoje.", "en": "No relevant events today."},
    "loading": {"pt": "Carregando…", "en": "Loading…"},
    "bias_bullish": {"pt": "ALTA", "en": "BULLISH"},
    "bias_bearish": {"pt": "BAIXA", "en": "BEARISH"},
    "bias_neutral": {"pt": "LATERAL", "en": "RANGE"},
    "regime_low": {"pt": "calmo", "en": "low"},
    "regime_mid": {"pt": "moderado", "en": "mid"},
    "regime_high": {"pt": "stress", "en": "high"},
    "term_contango": {"pt": "contango (calmo)", "en": "contango (calm)"},
    "term_backwardation": {"pt": "backwardation (stress)", "en": "backwardation (stress)"},
    "term_flat": {"pt": "achatada", "en": "flat"},
}


def t(key: str, language: Language) -> str:
    return STRINGS.get(key, {}).get(language, key)
