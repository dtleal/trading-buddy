"use client";

import { ArrowDown, ArrowUp, Undo2 } from "lucide-react";
import { bandTouchOdds, type BandOdds } from "@/lib/bollinger";
import type { BandScenario } from "@/lib/types";

/** Below this many analogs the figure is dimmed: still shown, but visibly
 * weaker, so a number built on a handful of cases never looks solid. */
const THIN_SAMPLE = 25;

/** Price is close enough to a band for "does it come back to the middle?" to
 * be a real question. In the middle of the band it is not — price is already
 * there, so the figure would be trivially high and mean nothing. */
const AT_BAND = 0.2;

/**
 * The two band reads, side by side: which band gets touched first (and how
 * likely), and — only when price is at a band — the chance of coming back to
 * the middle. Used on the Bandas chart and on the Dashboard flow strip.
 *
 * `closes` is the fallback for the touch odds when the backend scenario has
 * not arrived yet; without it that badge simply doesn't show.
 */
export function BandOddsBadges({
  scenario,
  closes,
}: {
  scenario?: BandScenario;
  closes?: number[];
}) {
  const odds = scenario ? scenarioOdds(scenario) : closes ? bandTouchOdds(closes) : null;
  const atBand =
    !!scenario && (scenario.pct_b <= AT_BAND || scenario.pct_b >= 1 - AT_BAND);
  return (
    <>
      {odds && <TouchOddsBadge odds={odds} measured={!!scenario} />}
      {scenario && atBand && <ReturnToMidBadge scenario={scenario} />}
    </>
  );
}

/** "Volta pra média": of the past visits to THIS band in THIS market state,
 * how many got back to the middle within the hour. Only shown when price is
 * actually at a band — mid-band it would be trivially high and mean nothing.
 * Sky = usually comes back, amber = usually keeps going (a break, not a
 * bounce), grey = coin flip. Every detail lives in the tooltip. */
function ReturnToMidBadge({ scenario }: { scenario: BandScenario }) {
  const r = scenario.return_to_mid;
  if (!r) return null;
  const p = Math.round(r.pct * 100);
  const tone =
    p >= 60
      ? "bg-sky-500/15 text-sky-400"
      : p <= 40
        ? "bg-amber-500/15 text-amber-400"
        : "bg-zinc-800 text-zinc-300";
  const side = scenario.pct_b < 0.5 ? "de baixo" : "de cima";
  const held =
    r.matched_on.length > 0
      ? `no mesmo estado de mercado (${r.matched_on.join(" + ")})`
      : "sem conseguir filtrar o estado de mercado";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums ${tone} ${
        r.regime_n < THIN_SAMPLE ? "opacity-60" : ""
      }`}
      title={
        `das ${r.regime_n} vezes que o preço esteve na banda ${side} ${held}, ` +
        `${p}% voltaram pra média em até 1h` +
        (r.median_bars != null ? ` (tipicamente ~${r.median_bars} candles)` : "") +
        ` · sem olhar o estado: ${pct(scenario.back_to_mid_pct)}` +
        (r.regime_n < THIN_SAMPLE ? " · amostra pequena, leia com reserva" : "")
      }
    >
      <Undo2 className="size-3.5" />
      {p}% média
    </span>
  );
}

/** Which band gets touched first, and how likely. `measured` = the share comes
 * from the symbol's own history; otherwise it is the random-walk estimate used
 * until enough history is stored. Grey = coin flip (≤55%). Price already at or
 * past a band shows "na banda" — that is where it IS, not a probability. */
function TouchOddsBadge({ odds, measured }: { odds: BandOdds; measured: boolean }) {
  const up = odds.at ? odds.at === "upper" : odds.pUp >= 0.5;
  const p = Math.round((up ? odds.pUp : 1 - odds.pUp) * 100);
  const undecided = !odds.at && p <= 55;
  const tone = undecided
    ? "bg-zinc-800 text-zinc-300"
    : up
      ? "bg-emerald-500/15 text-emerald-400"
      : "bg-red-500/15 text-red-400";
  const Arrow = up ? ArrowUp : ArrowDown;
  const side = up ? "cima" : "baixo";
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums ${tone}`}
      title={
        odds.at
          ? `preço já está na banda de ${side}`
          : measured
            ? `nas vezes anteriores que esteve aqui, ${p}% tocaram a banda de ${side} primeiro`
            : `${p}% de chance de tocar a banda de ${side} primeiro (estimativa por distância e volatilidade — ainda sem histórico suficiente para medir)`
      }
    >
      <Arrow className="size-3.5" />
      {odds.at ? "na banda" : `${p}%`}
    </span>
  );
}

/** The measured equivalent of `bandTouchOdds`: of the past visits here that
 * reached a band at all, the share that reached the upper one first. */
function scenarioOdds(s: BandScenario): BandOdds {
  const at = s.pct_b >= 1 ? "upper" : s.pct_b <= 0 ? "lower" : null;
  const up = s.upper_first?.n ?? 0;
  const down = s.lower_first?.n ?? 0;
  return { pUp: up + down > 0 ? up / (up + down) : 0.5, at };
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}
