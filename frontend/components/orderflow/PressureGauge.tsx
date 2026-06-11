"use client";

import { cn } from "@/lib/utils";
import type { OrderFlowSnapshot } from "@/lib/types";

/**
 * Buy/sell pressure derived from the synthesized tape: each up-tick is a buy,
 * each down-tick a sell (see the collector's quote-flow mode). `recent_trades`
 * is the short live window; the footprint delta sum is the cumulative lean.
 */
export function pressure(flow: OrderFlowSnapshot | undefined): {
  buy: number;
  sell: number;
  total: number;
  buyPct: number;
  delta: number;
  cumDelta: number;
} {
  let buy = 0;
  let sell = 0;
  for (const t of flow?.recent_trades ?? []) {
    if (t.side === "buy") buy += t.volume;
    else if (t.side === "sell") sell += t.volume;
  }
  const total = buy + sell;
  const cumDelta = (flow?.footprint ?? []).reduce((acc, b) => acc + b.delta, 0);
  return {
    buy,
    sell,
    total,
    buyPct: total > 0 ? buy / total : 0.5,
    delta: buy - sell,
    cumDelta,
  };
}

/**
 * Compact pressure marker: a green(buy)/red(sell) split bar with the short-term
 * delta in the middle. Meant to sit on top of a symbol column (the column header
 * already shows the symbol + freshness), so it carries no label of its own.
 */
export function PressureGauge({ flow }: { flow: OrderFlowSnapshot | undefined }) {
  const p = pressure(flow);
  const hasData = p.total > 0;
  const buyPctLabel = Math.round(p.buyPct * 100);
  const sellPctLabel = 100 - buyPctLabel;
  const lean = p.buyPct - 0.5;
  const leanTone =
    !hasData || Math.abs(lean) < 0.04
      ? "text-zinc-400"
      : lean > 0
        ? "text-emerald-400"
        : "text-rose-400";

  return (
    <div>
      <div className="relative flex h-4 w-full overflow-hidden rounded bg-zinc-800">
        <div
          className="h-full bg-emerald-500/80 transition-[width] duration-500"
          style={{ width: `${hasData ? p.buyPct * 100 : 50}%` }}
        />
        <div className="h-full flex-1 bg-rose-500/80 transition-[width] duration-500" />
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-zinc-950/60" />
      </div>
      <div className="mt-1 flex items-center justify-between text-[11px] tabular-nums">
        <span className="font-semibold text-emerald-400">{hasData ? `${buyPctLabel}%` : "—"}</span>
        <span className={cn("font-semibold", leanTone)}>
          {hasData ? `Δ ${p.delta > 0 ? "+" : ""}${Math.round(p.delta)}` : "aguardando"}
        </span>
        <span className="font-semibold text-rose-400">{hasData ? `${sellPctLabel}%` : "—"}</span>
      </div>
    </div>
  );
}
