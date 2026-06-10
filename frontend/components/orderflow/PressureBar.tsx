"use client";

import { useEffect, useState } from "react";
import { Gauge } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useOrderFlow } from "@/hooks/useOrderFlow";
import { cn } from "@/lib/utils";
import type { AssetSymbol, OrderFlowSnapshot } from "@/lib/types";

const FLOW_ASSETS: { key: AssetSymbol; label: string }[] = [
  { key: "USTEC", label: "USTEC" },
  { key: "SPX", label: "USA500" },
  { key: "GOLD", label: "GOLD" },
];

/**
 * Buying vs selling pressure strip — the first thing on the page.
 *
 * The CFD feed has no real traded volume, so pressure is the aggressor balance
 * of the synthesized tape: each up-tick counts as a buy, each down-tick as a
 * sell (see the collector's quote-flow mode). `recent_trades` is the live
 * short-window read; the footprint delta sum is the longer cumulative lean.
 */
export function PressureBar() {
  const { flows, status } = useOrderFlow();

  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 1_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  return (
    <Card>
      <CardContent className="py-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Gauge className="size-4 text-violet-400" />
            <span className="text-sm font-semibold uppercase tracking-wider text-zinc-200">
              Pressão compradora · vendedora
            </span>
          </div>
          <Badge tone={status === "open" ? "positive" : "negative"}>
            {status === "open" ? "ao vivo" : "desconectado"}
          </Badge>
        </div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {FLOW_ASSETS.map((a) => (
            <PressureGauge key={a.key} label={a.label} flow={flows[a.key]} now={now} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function pressure(flow: OrderFlowSnapshot | undefined): {
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

function PressureGauge({
  label,
  flow,
  now,
}: {
  label: string;
  flow: OrderFlowSnapshot | undefined;
  now: number;
}) {
  const p = pressure(flow);
  const asof = flow?.asof ? new Date(flow.asof).getTime() : null;
  const fresh = asof != null && now > 0 && now - asof <= 5_000;
  const hasData = p.total > 0;

  const buyPctLabel = Math.round(p.buyPct * 100);
  const sellPctLabel = 100 - buyPctLabel;
  // Lean by how far from balanced (50/50) the buyers are.
  const lean = p.buyPct - 0.5;
  const leanTone =
    !hasData || Math.abs(lean) < 0.04
      ? "text-zinc-400"
      : lean > 0
        ? "text-emerald-400"
        : "text-rose-400";

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
          {label}
        </span>
        <span
          className={cn(
            "inline-block size-2 rounded-full",
            !fresh ? "bg-zinc-600" : "animate-pulse bg-emerald-400",
          )}
        />
      </div>

      {/* split bar: green = buyers, red = sellers */}
      <div className="relative flex h-5 w-full overflow-hidden rounded bg-zinc-800">
        <div
          className="h-full bg-emerald-500/80 transition-[width] duration-500"
          style={{ width: `${hasData ? p.buyPct * 100 : 50}%` }}
        />
        <div className="h-full flex-1 bg-rose-500/80 transition-[width] duration-500" />
        {/* 50% reference line */}
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-zinc-950/60" />
      </div>

      <div className="mt-1.5 flex items-center justify-between text-[11px] tabular-nums">
        <span className="font-semibold text-emerald-400">{hasData ? `${buyPctLabel}%` : "—"}</span>
        <span className={cn("font-semibold", leanTone)}>
          {hasData ? `Δ ${p.delta > 0 ? "+" : ""}${Math.round(p.delta)}` : "aguardando feed"}
        </span>
        <span className="font-semibold text-rose-400">{hasData ? `${sellPctLabel}%` : "—"}</span>
      </div>

      <div className="mt-0.5 text-center text-[10px] uppercase tracking-wider text-zinc-500">
        Δ sessão {p.cumDelta > 0 ? "+" : ""}
        {Math.round(p.cumDelta)}
      </div>
    </div>
  );
}
