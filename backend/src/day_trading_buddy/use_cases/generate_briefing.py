"""Generate a pre-market macro briefing via the LLM gateway.

Output is persisted via the snapshot repository and cached in Redis by prompt
hash, so repeated invocations within a day return cheaply.
"""

from __future__ import annotations

import logging
from typing import Literal

from day_trading_buddy.core.enums import LLMOutputKind
from day_trading_buddy.core.interfaces import CacheStore, LLMGateway, SnapshotRepository
from day_trading_buddy.core.models import (
    DashboardTick,
    EconomicEvent,
    LLMOutput,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_PT = """\
You are a senior macro analyst writing a pre-market briefing for a Brazilian
day trader who trades **USTEC (Nasdaq 100), S&P 500 and Gold**. The trader does
their own price-action reading; your job is the macro / fundamentals layer.

Always reply in Brazilian Portuguese. Be concise, structured, and direct.
Format the response with these sections:

  1. **Quadro Macro** — 3 a 5 bullets sobre o ambiente macro do dia.
  2. **Calendário do Dia** — eventos de alto impacto com horário (US Eastern) e
     viés esperado em cada ativo (USTEC / SPX / Gold).
  3. **VIX** — leitura do regime atual e term structure.
  4. **Veredicto por Ativo** — para USTEC, SPX e Gold: viés (alta / baixa /
     lateral), confiança 0-100, e principal risco.
  5. **Risco do Dia** — uma frase: o que pode inverter tudo.

Não recomende entradas, stops ou take-profits. Foque em contexto.
"""

SYSTEM_PROMPT_EN = """\
You are a senior macro analyst writing a pre-market briefing for a day trader
who trades **USTEC (Nasdaq 100), S&P 500 and Gold**. The trader does their own
price-action reading; your job is the macro / fundamentals layer.

Reply in English. Be concise, structured, and direct. Format the response with:

  1. **Macro Picture** — 3-5 bullets on the macro environment for the day.
  2. **Today's Calendar** — high-impact events with US-Eastern time and
     expected bias per asset (USTEC / SPX / Gold).
  3. **VIX** — current regime and term structure read.
  4. **Per-Asset Verdict** — for USTEC, SPX and Gold: bias (bullish / bearish /
     range), confidence 0-100, and the main risk.
  5. **Day Risk** — one sentence: what could flip everything.

Do not recommend entries, stops, or take-profits. Focus on context.
"""


def _format_events(events: list[EconomicEvent]) -> str:
    if not events:
        return "(no high/medium-impact events)"
    lines: list[str] = []
    for e in events:
        line = f"- {e.scheduled_at.strftime('%H:%M UTC')} | {e.impact.value.upper()} | " f"{e.name}"
        if e.forecast or e.previous:
            line += f" (forecast={e.forecast or 'n/a'}, prev={e.previous or 'n/a'})"
        lines.append(line)
    return "\n".join(lines)


def _format_tick(tick: DashboardTick) -> str:
    parts: list[str] = ["## Market snapshot"]
    for asset, quote in tick.market.assets.items():
        ma_str = f"{quote.ma200_d:.2f}" if quote.ma200_d else "n/a"
        chg = f"{quote.change_pct:+.2f}%" if quote.change_pct is not None else "n/a"
        parts.append(f"- {asset.value}: price={quote.price:.2f}, change={chg}, MA200d={ma_str}")
    parts.append(
        f"- VIX: {tick.market.vix.vix:.2f} ({tick.market.vix.regime.value}), "
        f"term={tick.market.vix.term_structure.value}"
    )

    parts.append("\n## Macro indicators")
    for series_id, ind in tick.macro.indicators.items():
        parts.append(f"- {series_id}: {ind.value:.4f} (d1d={ind.delta_1d}, d1w={ind.delta_1w})")
    if tick.macro.fedwatch is not None:
        fw = tick.macro.fedwatch
        parts.append(
            f"- FedWatch: cut50={fw.cut_50:.0%}, cut25={fw.cut_25:.0%}, "
            f"hold={fw.hold:.0%}, hike25={fw.hike_25:.0%}, hike50={fw.hike_50:.0%}"
        )

    parts.append("\n## Today's events (US calendar)")
    parts.append(_format_events(tick.events_today))

    parts.append("\n## Recent headlines (last 60 min)")
    if not tick.recent_news:
        parts.append("- (none)")
    else:
        for item in tick.recent_news[:15]:
            parts.append(f"- [{item.source}] {item.headline}")
    return "\n".join(parts)


class GenerateBriefingUseCase:
    """Renders the tick payload, calls the LLM, persists the output."""

    def __init__(
        self,
        llm: LLMGateway,
        cache: CacheStore,
        repository: SnapshotRepository,
        *,
        language: Literal["pt", "en"] = "pt",
        cache_ttl_seconds: int = 24 * 3600,
    ) -> None:
        self._llm = llm
        self._cache = cache
        self._repository = repository
        self._language = language
        self._cache_ttl = cache_ttl_seconds

    async def execute(self, tick: DashboardTick) -> LLMOutput:
        system_prompt = SYSTEM_PROMPT_PT if self._language == "pt" else SYSTEM_PROMPT_EN
        user_prompt = _format_tick(tick)

        output = await self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            kind=LLMOutputKind.BRIEFING,
        )

        await self._cache.set(
            f"llm:response:{output.prompt_hash}", output.content, ttl_seconds=self._cache_ttl
        )
        await self._repository.save_llm_output(output)
        return output
