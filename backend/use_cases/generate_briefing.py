"""Generate a pre-market macro briefing via the LLM gateway.

Output is persisted via the snapshot repository and cached in Redis by prompt
hash, so repeated invocations within a day return cheaply.
"""

from __future__ import annotations

import logging
from typing import Literal

from core.enums import LLMOutputKind
from core.interfaces import CacheStore, LLMGateway, SnapshotRepository
from core.models import (
    DashboardTick,
    EconomicEvent,
    LLMOutput,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_PT = """\
You are a senior macro analyst writing a pre-market briefing for a Brazilian
day trader who trades **USTEC (Nasdaq 100), S&P 500, Gold and Bitcoin** on a
**5-minute chart**. The trader does their own price-action reading; your job is
the macro layer AND the daily-vs-intraday reconciliation.

Bitcoin trades as a **risk-on asset highly correlated with the tech indices**
(USTEC especially, and SPX): it tends to rally when risk appetite is on and
sell off in risk-off / high-VIX regimes. Read it through that lens and flag when
it diverges from USTEC/SPX, which is itself a signal.

The payload gives you two lenses per asset:
- **Daily structural** (price vs MA200d, day change %, macro indicators)
- **Intraday 5m** (HOD/LOD/VWAP/PDH/PDL, EMAs and SMA200 on 5m, swings, ATR)

Use both. When the daily lens disagrees with the 5m lens (price above MA200d
but below all 5m means, or vice versa), **call that out explicitly** — it is
the key signal for a 5m trader.

Always reply in Brazilian Portuguese. Be concise, structured, and direct.
Format the response with these sections:

  1. **Quadro Macro** — 3 a 5 bullets sobre o ambiente macro do dia.
  2. **Calendário do Dia** — eventos de alto impacto com horário (US Eastern) e
     viés esperado em cada ativo (USTEC / SPX / Gold / Bitcoin). Se vazio, declare.
  3. **VIX** — leitura do regime atual e term structure.
  4. **Veredicto por Ativo (dual-lens)** — para USTEC, SPX, Gold e Bitcoin:
     - **Estrutural (diário):** viés alta/baixa/lateral, distância da MM200d.
     - **Intraday (5m):** posição vs VWAP / EMAs / SMA200 5m, se rompeu
       PDH/PDL/HOD/LOD, breakouts recentes relevantes.
     - **Convergência ou divergência:** ✅ alinhados ou ⚠️ divergem (qual lado).
     - Confiança final 0-100 e principal risco.
  5. **Risco do Dia** — uma frase: o que pode inverter tudo.

Não recomende entradas, stops ou take-profits. Foque em contexto.
"""

SYSTEM_PROMPT_EN = """\
You are a senior macro analyst writing a pre-market briefing for a day trader
who trades **USTEC (Nasdaq 100), S&P 500, Gold and Bitcoin**. The trader does
their own price-action reading; your job is the macro / fundamentals layer.
Treat Bitcoin as a risk-on asset highly correlated with the tech indices
(USTEC/SPX) — flag when it diverges from them.

Reply in English. Be concise, structured, and direct. Format the response with:

  1. **Macro Picture** — 3-5 bullets on the macro environment for the day.
  2. **Today's Calendar** — high-impact events with US-Eastern time and
     expected bias per asset (USTEC / SPX / Gold / Bitcoin).
  3. **VIX** — current regime and term structure read.
  4. **Per-Asset Verdict** — for USTEC, SPX, Gold and Bitcoin: bias (bullish / bearish /
     range), confidence 0-100, and the main risk.
  5. **Day Risk** — one sentence: what could flip everything.

Do not recommend entries, stops, or take-profits. Focus on context.
"""


def _fmt_or_na(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


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


def format_tick_payload(tick: DashboardTick) -> str:
    """Render a DashboardTick as the markdown user-prompt sent to the LLM.

    Also reusable for `dtb snapshot` (dump-without-LLM) so an external Claude
    Code session can produce the briefing without calling the Anthropic API.
    Includes both the daily/structural lens (market quotes + MA200d) AND the
    5m intraday lens (per-asset HOD/LOD/VWAP/EMAs/SMA200/swings/ATR) — gives
    the consumer enough data to flag daily-vs-intraday divergence.
    """
    parts: list[str] = ["## Market snapshot (daily structural)"]
    for asset, quote in tick.market.assets.items():
        ma_str = f"{quote.ma200_d:.2f}" if quote.ma200_d else "n/a"
        chg = f"{quote.change_pct:+.2f}%" if quote.change_pct is not None else "n/a"
        parts.append(f"- {asset.value}: price={quote.price:.2f}, change={chg}, MA200d={ma_str}")
    parts.append(
        f"- VIX: {tick.market.vix.vix:.2f} ({tick.market.vix.regime.value}), "
        f"term={tick.market.vix.term_structure.value}"
    )

    parts.append("\n## Intraday (5m) per asset")
    if not tick.intraday_levels:
        parts.append("(no intraday data this tick)")
    else:
        for asset, lv in tick.intraday_levels.items():
            parts.append(
                f"\n### {asset.value} (last {lv.last_price:.2f}, asof {lv.asof.strftime('%H:%M UTC')})"
            )
            parts.append(
                f"- session: HOD={lv.hod:.2f}, LOD={lv.lod:.2f}, "
                f"VWAP={_fmt_or_na(lv.vwap)}, range={lv.hod - lv.lod:.2f}"
            )
            parts.append(
                f"- previous day: PDH={_fmt_or_na(lv.pdh)}, "
                f"PDL={_fmt_or_na(lv.pdl)}, PDC={_fmt_or_na(lv.pdc)}"
            )
            parts.append(
                f"- 5m MAs: EMA9={_fmt_or_na(lv.ema_9)}, EMA20={_fmt_or_na(lv.ema_20)}, "
                f"EMA50={_fmt_or_na(lv.ema_50)}, EMA200={_fmt_or_na(lv.ema_200)}, "
                f"SMA200={_fmt_or_na(lv.sma_200)}"
            )
            parts.append(
                f"- swings: high={_fmt_or_na(lv.last_swing_high)}, "
                f"low={_fmt_or_na(lv.last_swing_low)}"
            )
            parts.append(f"- ATR(14, 5m): {_fmt_or_na(lv.atr_14)}")

    if tick.breakouts_recent:
        parts.append("\n## Recent breakouts (Donchian N=20, multi-timeframe)")
        # Show at most 12 most recent so the prompt stays compact.
        for b in tick.breakouts_recent[:12]:
            direction = "↑" if b.direction.value == "up" else "↓"
            squeeze_tag = " (squeeze)" if b.squeeze else ""
            parts.append(
                f"- {b.asset.value} {b.timeframe.value} {direction} @ {b.close:.2f} "
                f"(level {b.level:.2f}, expansion {b.expansion_ratio:.2f}× ATR, "
                f"strength {b.strength:.0f}/100){squeeze_tag} "
                f"— {b.signal_bar_at.strftime('%H:%M UTC')}"
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
        user_prompt = format_tick_payload(tick)

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
