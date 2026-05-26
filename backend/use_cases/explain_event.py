"""Explain an upcoming or just-released economic event via the LLM gateway."""

from __future__ import annotations

import logging
from typing import Literal

from core.enums import LLMOutputKind
from core.interfaces import CacheStore, LLMGateway, SnapshotRepository
from core.models import EconomicEvent, LLMOutput

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_PT_PRE = """\
You are a macro analyst. The user trades USTEC, S&P 500 and Gold.

Reply in Brazilian Portuguese, in 4-6 short bullets:
- O que é o indicador (1 linha).
- Por que o mercado se importa hoje.
- Cenário se vier ACIMA do forecast (impacto em USTEC / SPX / Gold).
- Cenário se vier ABAIXO do forecast (impacto em USTEC / SPX / Gold).
- Faixa de volatilidade esperada para o release (qualitativa).

Sem recomendar trades.
"""

SYSTEM_PROMPT_PT_POST = """\
You are a macro analyst. The user trades USTEC, S&P 500 and Gold.

A US release just printed. Reply in Brazilian Portuguese, in 4-6 short bullets:
- Como o número saiu vs forecast e previous.
- Leitura: hawkish, dovish, em linha.
- Impacto imediato esperado em USTEC / SPX / Gold.
- Impacto no VIX e na curva de juros.
- Uma frase: o trader deve operar normal, reduzir risco ou aguardar?

Sem recomendar entradas, stops ou take-profits.
"""

SYSTEM_PROMPT_EN_PRE = """\
You are a macro analyst. The user trades USTEC, S&P 500 and Gold.

Reply in English in 4-6 short bullets:
- What the indicator is (one line).
- Why the market cares today.
- Scenario if it prints ABOVE forecast (impact on USTEC / SPX / Gold).
- Scenario if it prints BELOW forecast (impact on USTEC / SPX / Gold).
- Expected volatility band for the release (qualitative).

Do not recommend trades.
"""

SYSTEM_PROMPT_EN_POST = """\
You are a macro analyst. The user trades USTEC, S&P 500 and Gold.

A US release just printed. Reply in English in 4-6 short bullets:
- How the number came in vs forecast and previous.
- Read: hawkish, dovish, or in-line.
- Expected immediate impact on USTEC / SPX / Gold.
- Impact on VIX and the rate curve.
- One sentence: should the trader trade normally, reduce risk, or wait?

Do not recommend entries, stops, or take-profits.
"""


def _system_prompt(mode: Literal["pre", "post"], language: Literal["pt", "en"]) -> str:
    if language == "pt":
        return SYSTEM_PROMPT_PT_PRE if mode == "pre" else SYSTEM_PROMPT_PT_POST
    return SYSTEM_PROMPT_EN_PRE if mode == "pre" else SYSTEM_PROMPT_EN_POST


def _format_event(event: EconomicEvent) -> str:
    return (
        f"Event: {event.name}\n"
        f"Currency: {event.currency}\n"
        f"Impact: {event.impact.value}\n"
        f"Scheduled (UTC): {event.scheduled_at.isoformat()}\n"
        f"Forecast: {event.forecast or 'n/a'}\n"
        f"Previous: {event.previous or 'n/a'}\n"
        f"Actual: {event.actual or 'not released yet'}\n"
    )


class ExplainEventUseCase:
    """Pre- or post-event LLM briefing for a specific release."""

    def __init__(
        self,
        llm: LLMGateway,
        cache: CacheStore,
        repository: SnapshotRepository,
        *,
        language: Literal["pt", "en"] = "pt",
        cache_ttl_seconds: int = 3 * 3600,
    ) -> None:
        self._llm = llm
        self._cache = cache
        self._repository = repository
        self._language = language
        self._cache_ttl = cache_ttl_seconds

    async def execute(
        self,
        event: EconomicEvent,
        mode: Literal["pre", "post"],
    ) -> LLMOutput:
        kind = LLMOutputKind.EVENT_PRE if mode == "pre" else LLMOutputKind.EVENT_POST
        system_prompt = _system_prompt(mode, self._language)
        user_prompt = _format_event(event)

        output = await self._llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            kind=kind,
        )

        await self._cache.set(
            f"llm:response:{output.prompt_hash}", output.content, ttl_seconds=self._cache_ttl
        )
        await self._repository.save_llm_output(output)
        return output
