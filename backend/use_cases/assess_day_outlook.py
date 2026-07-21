"""Assess whether the session promises real movement or is a thin/chop trap.

This is the "Perfil do Dia" gate. A flow trader gets eaten on days like a US
bank holiday: a few opening candles move, then participation collapses and
price oscillates — buy candle, sell candle, no net travel — while spreads stay
wide enough to bleed an account. Those days have *detectable precursors*:

  - a bank holiday in the driving currency (cash market closed / half day),
  - no scheduled high-impact catalyst to inject directional flow,
  - a compressed volatility regime (low VIX),
  - an opening range that is narrow relative to the daily ATR,
  - and — the empirical core — live tick volume running below the same
    time-of-day baseline (fed by the MT5 collector).

`execute()` is a pure function over already-fetched data: it does no I/O, so it
is trivial to unit-test against a holiday day vs a CPI day. It returns a
`DayOutlook` with a 0-100 movement-potential score, a discrete `DayRegime`
go/no-go gate, a one-line PT headline, and a rationale list explaining every
contributing factor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Sequence

from core.enums import AssetSymbol, DayRegime, ImpactLevel, TermStructure, VixRegime
from core.models import (
    DayOutlook,
    EconomicEvent,
    IntradayLevels,
    SessionLiquidity,
    VixSnapshot,
)

# Currencies whose holidays gut the instruments the user trades (US index +
# gold CFDs). A holiday here is the single strongest thin-session signal.
_DRIVING_CURRENCIES = {"USD"}

# Score is anchored at 50 (an ordinary session) and nudged by each signal.
_NEUTRAL_SCORE = 50.0


@dataclass(frozen=True)
class DayOutlookThresholds:
    """Tunable score adjustments. Defaults are deliberately conservative — the
    gate should err toward warning the trader off marginal days."""

    holiday_penalty: float = 35.0
    no_catalyst_penalty: float = 10.0  # zero high-impact events scheduled today
    catalyst_upcoming_bonus: float = 18.0  # high-impact event still ahead
    catalyst_released_bonus: float = 6.0  # high-impact event(s) already out
    extra_catalyst_bonus: float = 6.0  # 2+ high-impact events
    vix_low_penalty: float = 8.0  # compressed vol regime
    vix_high_bonus: float = 12.0  # expansive vol regime
    backwardation_bonus: float = 5.0  # short-term stress in VIX term structure
    or_compression_penalty: float = 8.0  # opening range < compression×ATR
    or_expansion_bonus: float = 8.0  # opening range > expansion×ATR
    or_compression_ratio: float = 0.5
    or_expansion_ratio: float = 1.2

    # MT5 tick-volume ratio bands (realized / same-time-of-day baseline).
    liq_very_thin_below: float = 0.5
    liq_thin_below: float = 0.75
    liq_high_above: float = 1.25
    liq_very_high_above: float = 1.75
    liq_very_thin_penalty: float = 20.0
    liq_thin_penalty: float = 10.0
    liq_high_bonus: float = 10.0
    liq_very_high_bonus: float = 18.0

    # Score → regime cutoffs.
    thin_at_or_below: float = 38.0
    expansion_at_or_above: float = 64.0


@dataclass
class _Score:
    """Mutable accumulator so each rule can append its own rationale line."""

    value: float = _NEUTRAL_SCORE
    rationale: list[str] = field(default_factory=list)

    def add(self, delta: float, reason: str) -> None:
        if delta == 0:
            return
        self.value += delta
        sign = "+" if delta > 0 else "−"
        self.rationale.append(f"{reason} ({sign}{abs(delta):.0f})")


class AssessDayOutlookUseCase:
    """Pure assessor. Inject thresholds; call `execute(...)` per tick."""

    def __init__(self, thresholds: DayOutlookThresholds | None = None) -> None:
        self._t = thresholds or DayOutlookThresholds()

    def execute(
        self,
        *,
        now: datetime,
        events_today: Sequence[EconomicEvent],
        vix: VixSnapshot | None = None,
        levels: dict[AssetSymbol, IntradayLevels] | None = None,
        liquidity: dict[AssetSymbol, SessionLiquidity] | None = None,
    ) -> DayOutlook:
        t = self._t
        s = _Score()

        is_holiday = self._apply_holiday(s, events_today)
        high_impact_count = self._apply_catalysts(s, events_today, now)
        self._apply_vix(s, vix)
        # On a US holiday the index cash market is closed, so the 5m yfinance
        # bars are stale/degenerate and the opening-range vs ATR ratio is
        # meaningless (it can read as a huge fake "expansion"). Skip it — the
        # holiday signal already dominates and the live MT5 liquidity, if fed,
        # carries the real read of how thin the session is.
        if not is_holiday:
            self._apply_opening_range(s, levels)
        liq_ratio = self._apply_liquidity(s, liquidity)

        score = max(0.0, min(100.0, s.value))
        regime = self._regime(score)
        headline = self._headline(regime, is_holiday, high_impact_count, liq_ratio)

        return DayOutlook(
            asof=now,
            score=score,
            regime=regime,
            headline=headline,
            rationale=s.rationale,
            is_us_holiday=is_holiday,
            high_impact_count=high_impact_count,
            liquidity_ratio=liq_ratio,
        )

    # --- individual signals ------------------------------------------------

    def _apply_holiday(self, s: _Score, events: Sequence[EconomicEvent]) -> bool:
        holiday = next(
            (
                e
                for e in events
                if e.impact is ImpactLevel.HOLIDAY and e.currency.upper() in _DRIVING_CURRENCIES
            ),
            None,
        )
        if holiday is None:
            return False
        s.add(-self._t.holiday_penalty, f"Feriado nos EUA ({holiday.name}) — liquidez reduzida")
        return True

    def _apply_catalysts(self, s: _Score, events: Sequence[EconomicEvent], now: datetime) -> int:
        high = [e for e in events if e.impact is ImpactLevel.HIGH]
        count = len(high)
        if count == 0:
            s.add(-self._t.no_catalyst_penalty, "Nenhum evento de alto impacto agendado")
            return 0

        upcoming = [e for e in high if e.scheduled_at > now]
        if upcoming:
            nxt = min(upcoming, key=lambda e: e.scheduled_at)
            when = nxt.scheduled_at.strftime("%H:%M UTC")
            s.add(
                self._t.catalyst_upcoming_bonus,
                f"Evento de alto impacto às {when} ({nxt.name}) — catalisador à frente",
            )
        else:
            s.add(self._t.catalyst_released_bonus, "Evento de alto impacto já divulgado hoje")
        if count >= 2:
            s.add(self._t.extra_catalyst_bonus, f"{count} eventos de alto impacto no dia")
        return count

    def _apply_vix(self, s: _Score, vix: VixSnapshot | None) -> None:
        if vix is None:
            return
        if vix.regime is VixRegime.LOW:
            s.add(-self._t.vix_low_penalty, f"VIX em regime baixo ({vix.vix:.1f}) — vol comprimida")
        elif vix.regime is VixRegime.HIGH:
            s.add(self._t.vix_high_bonus, f"VIX em regime alto ({vix.vix:.1f}) — ranges amplos")
        if vix.term_structure is TermStructure.BACKWARDATION:
            s.add(
                self._t.backwardation_bonus, "Estrutura a termo do VIX em backwardation (estresse)"
            )

    def _apply_opening_range(
        self, s: _Score, levels: dict[AssetSymbol, IntradayLevels] | None
    ) -> None:
        if not levels:
            return
        ratios: list[float] = []
        for lv in levels.values():
            if lv.orh is None or lv.orl is None or not lv.atr_14:
                continue
            ratios.append((lv.orh - lv.orl) / lv.atr_14)
        if not ratios:
            return
        avg = sum(ratios) / len(ratios)
        if avg < self._t.or_compression_ratio:
            s.add(
                -self._t.or_compression_penalty,
                f"Abertura comprimida (range = {avg:.2f}× ATR)",
            )
        elif avg > self._t.or_expansion_ratio:
            s.add(self._t.or_expansion_bonus, f"Abertura expandida (range = {avg:.2f}× ATR)")

    def _apply_liquidity(
        self, s: _Score, liquidity: dict[AssetSymbol, SessionLiquidity] | None
    ) -> float | None:
        """Fold the live MT5 readings into the score.

        Two ratios come off the same MT5 candles: tick **volume** (participation)
        and session **range** (how far price has actually travelled — the "candles
        minúsculos" signal). A day is thin if EITHER is below normal, so we score
        on the *worse* of the two; both numbers go into the rationale. Returns the
        volume ratio for the banner's `liquidity_ratio` field."""
        if not liquidity:
            return None
        vol_ratios = [lq.ratio for lq in liquidity.values() if lq.baseline_volume > 0]
        range_ratios = [lq.range_ratio for lq in liquidity.values() if lq.range_ratio is not None]
        if not vol_ratios:
            return None
        vol = median(vol_ratios)
        rng = median(range_ratios) if range_ratios else None
        # Worse-of drives the verdict; report whichever signals are present.
        activity = min(vol, rng) if rng is not None else vol

        t = self._t
        detail = f"volume {vol * 100:.0f}%"
        if rng is not None:
            detail += f", candles {rng * 100:.0f}%"
        detail += " do normal (MT5)"

        if activity < t.liq_very_thin_below:
            s.add(-t.liq_very_thin_penalty, f"Atividade muito baixa — {detail}")
        elif activity < t.liq_thin_below:
            s.add(-t.liq_thin_penalty, f"Atividade abaixo do normal — {detail}")
        elif activity > t.liq_very_high_above:
            s.add(t.liq_very_high_bonus, f"Atividade muito acima do normal — {detail}")
        elif activity > t.liq_high_above:
            s.add(t.liq_high_bonus, f"Atividade acima do normal — {detail}")
        return vol

    # --- verdict -----------------------------------------------------------

    def _regime(self, score: float) -> DayRegime:
        if score <= self._t.thin_at_or_below:
            return DayRegime.THIN
        if score >= self._t.expansion_at_or_above:
            return DayRegime.EXPANSION
        return DayRegime.NORMAL

    def _headline(
        self,
        regime: DayRegime,
        is_holiday: bool,
        high_impact_count: int,
        liq_ratio: float | None,
    ) -> str:
        if regime is DayRegime.THIN:
            if is_holiday:
                why = "feriado nos EUA, pouca liquidez"
            elif liq_ratio is not None and liq_ratio < self._t.liq_thin_below:
                why = f"volume rodando a {liq_ratio * 100:.0f}% do normal"
            elif high_impact_count == 0:
                why = "sem catalisador no dia"
            else:
                why = "baixa participação"
            return f"⚠️ Dia FRACO — {why}. Risco de chop, opere pequeno ou fique de fora."
        if regime is DayRegime.EXPANSION:
            why = (
                "catalisador de alto impacto à frente"
                if high_impact_count
                else "participação elevada"
            )
            return f"🚀 Dia de EXPANSÃO — {why}. Espere movimento."
        return "Dia NORMAL — movimento dentro do comum."


__all__ = ["AssessDayOutlookUseCase", "DayOutlookThresholds"]
