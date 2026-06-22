"use client";

import { useEffect, useState } from "react";
import { LayoutGrid } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BidAskChart } from "./BidAskChart";
import { PressureGauge } from "./PressureGauge";
import { PositionPanel } from "./PositionPanel";
import { AutoCloseControl } from "./AutoCloseControl";
import { ScalperBotControl } from "./ScalperBotControl";
import { FootprintPanel } from "./FootprintPanel";
import { TapePanel } from "./TapePanel";
import { useOrderFlow } from "@/hooks/useOrderFlow";
import { useAutoClose } from "@/hooks/useAutoClose";
import { useScalperBot } from "@/hooks/useScalperBot";
import { cn } from "@/lib/utils";
import type { AssetSymbol, LiveActivity, OrderFlowSnapshot, SessionLiquidity } from "@/lib/types";

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
  const { status: autoClose, arm, disarm, closeSymbol } = useAutoClose();
  const { status: bot, arm: armBot, disarm: disarmBot } = useScalperBot();
  const executionEnabled = autoClose?.enabled ?? false;

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
              <CardTitle>Fluxo · Pressão · Bid/Ask · Footprint · Tape</CardTitle>
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
      <CardContent className="flex flex-col gap-4">
        <ScalperBotControl status={bot} arm={armBot} disarm={disarmBot} />
        <AutoCloseControl status={autoClose} arm={arm} disarm={disarm} />
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          {FLOW_ASSETS.map((a) => (
            <SymbolColumn
              key={a.key}
              label={a.label}
              symbol={a.key}
              flow={flows[a.key]}
              now={now}
              status={status}
              executionEnabled={executionEnabled}
              onCloseSymbol={closeSymbol}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function SymbolColumn({
  label,
  symbol,
  flow,
  now,
  status,
  executionEnabled,
  onCloseSymbol,
}: {
  label: string;
  symbol: AssetSymbol;
  flow: OrderFlowSnapshot | undefined;
  now: number;
  status: "connecting" | "open" | "reconnecting" | "closed";
  executionEnabled: boolean;
  onCloseSymbol: (symbol: string) => Promise<void>;
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
          <LiquidityChip liquidity={flow.liquidity} live={flow.live_activity} />
          {flow.positions.length > 0 && (
            <FlowBlock title="Posição aberta (MT5)">
              <PositionPanel
                label={label}
                symbol={symbol}
                positions={flow.positions}
                signals={flow.signals}
                executionEnabled={executionEnabled}
                onCloseAll={onCloseSymbol}
              />
            </FlowBlock>
          )}
          <FlowBlock title="Pressão (compra · venda)">
            <PressureGauge flow={flow} />
          </FlowBlock>
          <FlowBlock title="Bid · Ask (tempo real)">
            <BidAskChart flow={flow} now={now} />
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

/**
 * Per-asset activity gauge. Two layers:
 *  - **Live** (always, the instant footprint arrives): current candle size +
 *    volume per bar, read straight off the live flow — answers "is the market
 *    moving right now". No baseline needed.
 *  - **vs normal** (when the collector's baseline is in): tick volume + session
 *    range as a % of the same-time-of-day median; the worse of the two drives
 *    the color/label so a dead session lights up red.
 */
function LiquidityChip({
  liquidity,
  live,
}: {
  liquidity: SessionLiquidity | null;
  live: LiveActivity | null;
}) {
  const hasBaseline = !!liquidity && liquidity.baseline_volume > 0;

  // No baseline yet → show the live read if we have footprint, else waiting.
  if (!hasBaseline) {
    if (!live || live.sampled_bars === 0) {
      return (
        <div className="rounded-md border border-zinc-800 bg-zinc-900/40 px-2 py-1.5 text-[11px] text-zinc-500">
          Atividade: <span className="text-zinc-400">aguardando fluxo do MT5…</span>
        </div>
      );
    }
    const perMin = live.volume_per_bar * (60 / Math.max(1, live.interval_seconds));
    return (
      <div className="rounded-md border border-zinc-700/60 bg-zinc-900/50 px-2 py-1.5 text-zinc-200">
        <div className="mb-0.5 flex items-center justify-between text-[11px] font-semibold">
          <span className="uppercase tracking-wider">Atividade · tempo real</span>
          <span className="text-[10px] font-normal text-zinc-500">{live.sampled_bars} barras</span>
        </div>
        <div className="flex items-center justify-between text-[11px] tabular-nums text-zinc-300">
          <span>Candle ~{live.range_per_bar.toFixed(1)} pts</span>
          <span>~{Math.round(perMin)} vol/min</span>
        </div>
        <div className="mt-0.5 text-[10px] text-zinc-500">
          baseline “% do normal” aparece quando o collector novo subir
        </div>
      </div>
    );
  }

  const vol = liquidity!.ratio;
  const rng = liquidity!.range_ratio; // may be null until baseline exists
  const worst = rng != null ? Math.min(vol, rng) : vol;
  const thin = worst < 0.75;
  const high = worst > 1.25;
  const tone = thin
    ? "border-rose-700/60 bg-rose-950/30 text-rose-200"
    : high
      ? "border-emerald-700/60 bg-emerald-950/30 text-emerald-200"
      : "border-zinc-700/60 bg-zinc-900/50 text-zinc-200";
  const label = thin ? "DIA FRACO" : high ? "ATIVO" : "normal";

  return (
    <div className={cn("rounded-md border px-2 py-1.5", tone)}>
      <div className="mb-1 flex items-center justify-between text-[11px] font-semibold">
        <span className="uppercase tracking-wider">Atividade · {label}</span>
      </div>
      <ActivityBar caption="Volume" ratio={vol} thin={thin} high={high} />
      {rng != null && (
        <div className="mt-1">
          <ActivityBar caption="Candles" ratio={rng} thin={thin} high={high} />
        </div>
      )}
    </div>
  );
}

/** One labelled bar: fills proportional to ratio (100% mark = normal session). */
function ActivityBar({
  caption,
  ratio,
  thin,
  high,
}: {
  caption: string;
  ratio: number;
  thin: boolean;
  high: boolean;
}) {
  // Cap at 200% so a spike doesn't blow out the bar.
  const fillPct = Math.min(100, (ratio / 2) * 100);
  const barColor = thin ? "bg-rose-500/80" : high ? "bg-emerald-500/80" : "bg-zinc-500/80";
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] tabular-nums text-zinc-400">
        <span>{caption}</span>
        <span>{Math.round(ratio * 100)}% do normal</span>
      </div>
      <div className="relative mt-0.5 h-1.5 w-full overflow-hidden rounded bg-zinc-800">
        <div
          className={cn("h-full transition-[width] duration-500", barColor)}
          style={{ width: `${fillPct}%` }}
        />
        <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-zinc-950/70" />
      </div>
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
