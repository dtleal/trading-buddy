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
import type { AssetSymbol } from "@/lib/types";

// Order flow only covers indices + gold. Display labels follow the trader's
// MT5 naming (S&P is "USA500"); the backend key stays SPX.
const FLOW_ASSETS: { key: AssetSymbol; label: string }[] = [
  { key: "USTEC", label: "USTEC" },
  { key: "SPX", label: "USA500" },
  { key: "GOLD", label: "GOLD" },
];

/**
 * Live order-flow section: DOM ladder + footprint + tape for the selected
 * asset. Streams from /ws/orderflow (separate channel from the 5m tick),
 * which the Windows MT5 collector feeds. Empty until the collector connects.
 */
export function OrderFlowSection() {
  const { flows, status } = useOrderFlow();
  const [selected, setSelected] = useState<AssetSymbol>("USTEC");
  const flow = flows[selected];

  // Ticking clock so staleness recomputes from state (pure render), not from
  // Date.now() called during render.
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0); // async — avoids setState-in-effect-body
    const id = setInterval(tick, 5_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);

  const asof = flow?.asof ? new Date(flow.asof).getTime() : null;
  const stale = asof === null || now === 0 || now - asof > 15_000;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <LayoutGrid className="size-4 text-violet-400" />
            <div>
              <CardTitle>Fluxo · DOM · Footprint · Tape</CardTitle>
              <CardDescription>
                Order book, volume executado por preço e fita — ao vivo via MT5
              </CardDescription>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={status === "open" ? (stale ? "warning" : "positive") : "negative"}>
              {status === "open" ? (stale ? "sem dados" : "ao vivo") : "desconectado"}
            </Badge>
            <div className="flex gap-1">
              {FLOW_ASSETS.map((a) => (
                <button
                  key={a.key}
                  onClick={() => setSelected(a.key)}
                  className={cn(
                    "rounded-md px-3 py-1 text-xs font-semibold uppercase tracking-wider transition-colors",
                    selected === a.key
                      ? "bg-violet-500/20 text-violet-200 ring-1 ring-violet-500/40"
                      : "text-zinc-400 hover:bg-zinc-800/60",
                  )}
                >
                  {a.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {!flow ? (
          <p className="text-sm text-zinc-500">
            Aguardando o coletor MT5… inicie o collector no Windows e confirme
            <code className="mx-1 rounded bg-zinc-800 px-1">ORDERFLOW_ENABLED=true</code>
            no backend.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <FlowColumn title="DOM (liquidez em repouso)">
              <DomLadder book={flow.book} />
            </FlowColumn>
            <FlowColumn title="Footprint (volume executado)">
              <FootprintPanel bars={flow.footprint} />
            </FlowColumn>
            <FlowColumn title="Tape (time & sales)">
              <TapePanel trades={flow.recent_trades} />
            </FlowColumn>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function FlowColumn({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
        {title}
      </div>
      {children}
    </div>
  );
}
