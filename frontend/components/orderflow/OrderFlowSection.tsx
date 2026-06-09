"use client";

import { useEffect, useState } from "react";
import { LayoutGrid } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DomLadder } from "./DomLadder";
import { FootprintPanel } from "./FootprintPanel";
import { TapePanel } from "./TapePanel";
import { useOrderFlow } from "@/hooks/useOrderFlow";
import { cn } from "@/lib/utils";
import type { AssetSymbol, OrderFlowSnapshot } from "@/lib/types";

const FLOW_ASSETS: { key: AssetSymbol; label: string }[] = [
  { key: "USTEC", label: "USTEC" },
  { key: "SPX", label: "USA500" },
  { key: "GOLD", label: "GOLD" },
];

/**
 * Live order-flow strip. Renders the 3 assets simultaneously, each as its own
 * column (DOM ladder on top, footprint in the middle, tape at the bottom).
 * Designed to sit above the VIX hero so it is the first thing on screen.
 */
export function OrderFlowSection() {
  const { flows, status } = useOrderFlow();

  // Ticking clock so per-symbol staleness is reactive without calling Date.now()
  // during render.
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

  // Aggregate "is anything fresh?" for the header badge.
  const anyFresh = FLOW_ASSETS.some((a) => {
    const f = flows[a.key];
    if (!f) return false;
    const asof = new Date(f.asof).getTime();
    return now > 0 && now - asof <= 5_000;
  });

  // Whichever symbol has a source string wins — in practice all symbols share
  // it (one collector per backend today) but we don't enforce that.
  const source =
    FLOW_ASSETS.map((a) => flows[a.key]?.source).find((s): s is string => !!s) ?? null;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <LayoutGrid className="size-4 text-violet-400" />
            <div>
              <CardTitle>Fluxo · DOM · Footprint · Tape</CardTitle>
              <CardDescription>
                USTEC · USA500 · GOLD em tempo real (MT5)
              </CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {source && (
              <Badge tone="neutral">
                <span className="text-zinc-500">fonte:</span>{" "}
                <span className="text-zinc-200">{source}</span>
              </Badge>
            )}
            <Badge tone={status === "open" ? (anyFresh ? "positive" : "warning") : "negative"}>
              {status === "open" ? (anyFresh ? "ao vivo" : "sem dados") : "desconectado"}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          {FLOW_ASSETS.map((a) => (
            <SymbolColumn
              key={a.key}
              label={a.label}
              flow={flows[a.key]}
              now={now}
              status={status}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function SymbolColumn({
  label,
  flow,
  now,
  status,
}: {
  label: string;
  flow: OrderFlowSnapshot | undefined;
  now: number;
  status: "connecting" | "open" | "reconnecting" | "closed";
}) {
  const asof = flow?.asof ? new Date(flow.asof).getTime() : null;
  const ageMs = asof != null && now > 0 ? now - asof : null;
  const fresh = ageMs != null && ageMs <= 5_000;

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold uppercase tracking-wider text-zinc-200">
          {label}
        </div>
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider">
          <span
            className={cn(
              "inline-block size-2 rounded-full",
              status !== "open"
                ? "bg-zinc-600"
                : fresh
                  ? "animate-pulse bg-emerald-400"
                  : "bg-amber-500",
            )}
          />
          <span className="text-zinc-500">
            {!flow
              ? "sem feed"
              : fresh
                ? `${ageMs}ms`
                : ageMs != null
                  ? `${Math.round(ageMs / 1000)}s atrás`
                  : "—"}
          </span>
        </div>
      </div>

      {!flow ? (
        <p className="text-xs text-zinc-500">
          Aguardando o coletor MT5… inicie o collector no Windows.
        </p>
      ) : (
        <>
          <FlowBlock title="DOM (liquidez em repouso)">
            <DomLadder book={flow.book} />
          </FlowBlock>
          <FlowBlock title="Footprint (volume executado)">
            <FootprintPanel bars={flow.footprint} />
          </FlowBlock>
          <FlowBlock title="Tape (time & sales)">
            <TapePanel trades={flow.recent_trades} />
          </FlowBlock>
        </>
      )}
    </div>
  );
}

function FlowBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-2">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        {title}
      </div>
      {children}
    </div>
  );
}
