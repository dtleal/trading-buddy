"use client";

import { ArrowUpToLine, ArrowDownToLine } from "lucide-react";
import { cn, fmtPrice, priceDigits } from "@/lib/utils";
import type { LevelProximity } from "@/lib/alerts/levels";

/**
 * Loud, always-on banner that lights up the instant any symbol's live price
 * approaches yesterday's high/low. Amber (pulsing border) when "approaching",
 * red (pulsing fill) when at/through the level. Hidden entirely when nothing is
 * close, so its mere appearance is the signal.
 */
export function LevelProximityBanner({ proximities }: { proximities: LevelProximity[] }) {
  if (proximities.length === 0) return null;

  // Most urgent first (at > near, then nearest).
  const sorted = [...proximities].sort((a, b) => {
    if (a.tier !== b.tier) return a.tier === "at" ? -1 : 1;
    return a.atrGap - b.atrGap;
  });
  const anyAt = sorted.some((p) => p.tier === "at");

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border-2 p-3",
        anyAt
          ? "animate-pulse border-rose-500 bg-rose-950/50"
          : "animate-pulse border-amber-500 bg-amber-950/40",
      )}
    >
      <div
        className={cn(
          "text-xs font-bold uppercase tracking-widest",
          anyAt ? "text-rose-300" : "text-amber-300",
        )}
      >
        ⚠ Preço nos níveis de ontem
      </div>
      <div className="flex flex-wrap gap-2">
        {sorted.map((p) => (
          <ProximityChip key={`${p.symbol}:${p.kind}`} p={p} />
        ))}
      </div>
    </div>
  );
}

function ProximityChip({ p }: { p: LevelProximity }) {
  const at = p.tier === "at";
  const isHigh = p.kind === "PDH";
  const Icon = isHigh ? ArrowUpToLine : ArrowDownToLine;
  const state = at ? (p.broken ? "ROMPEU" : "NA") : "chegando";
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm font-semibold tabular-nums",
        at
          ? "border-rose-500 bg-rose-500/20 text-rose-100"
          : "border-amber-500/70 bg-amber-500/15 text-amber-100",
      )}
    >
      <Icon className="size-4 shrink-0" />
      <span className="uppercase tracking-wider">{p.label}</span>
      <span className={cn("text-[10px] uppercase", at ? "text-rose-300" : "text-amber-300")}>
        {state} {p.kind}
      </span>
      <span className="text-zinc-100">{fmtPrice(p.target)}</span>
      <span className="text-[11px] font-normal text-zinc-400">
        {p.gap > 0 ? `${fmtPrice(Math.abs(p.gap), priceDigits(p.target))} pts` : "rompido"}
      </span>
    </div>
  );
}
