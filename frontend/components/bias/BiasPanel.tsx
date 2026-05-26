"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { BiasLevel, BiasReport, DashboardTick } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Per-asset bias gauge. Mirrors the CLI "Viés por ativo" table.
 *
 * Score scale: ≥60 = ALTA, ≤40 = BAIXA, else LATERAL.
 * Components are technical / macro / sentiment, each 0-100.
 */
export function BiasPanel({ tick }: { tick: DashboardTick | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Viés por ativo</CardTitle>
        <CardDescription>
          Score 0-100 combinando técnico (40%) + macro (30%) + sentimento (30%)
        </CardDescription>
      </CardHeader>
      <CardContent>
        {tick ? (
          <div className="space-y-3">
            {Object.values(tick.bias).map((report) => (
              <BiasRow key={report.asset} report={report} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-zinc-500">Aguardando primeiro tick…</p>
        )}
      </CardContent>
    </Card>
  );
}

function BiasRow({ report }: { report: BiasReport }) {
  const { asset, score, level, components } = report;
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="font-semibold tracking-wider text-zinc-100">{asset}</span>
        <div className="flex items-center gap-2">
          <span className="text-2xl font-semibold tabular-nums">{score.toFixed(0)}</span>
          <BiasBadge level={level} />
        </div>
      </div>
      <ScoreBar value={score} />
      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <ComponentCell label="Técnico" value={components.technical} />
        <ComponentCell label="Macro" value={components.macro} />
        <ComponentCell label="Sentim." value={components.sentiment} />
      </div>
    </div>
  );
}

function BiasBadge({ level }: { level: BiasLevel }) {
  if (level === "bullish") return <Badge tone="positive">ALTA</Badge>;
  if (level === "bearish") return <Badge tone="negative">BAIXA</Badge>;
  return <Badge tone="warning">LATERAL</Badge>;
}

function ScoreBar({ value }: { value: number }) {
  // Three-zone bar: 0-40 red, 41-59 amber, 60-100 emerald. Marker shows the score.
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className="mt-2 relative h-2 w-full overflow-hidden rounded-full bg-zinc-800">
      <div
        className="absolute inset-y-0 left-0 bg-red-700/40"
        style={{ width: "40%" }}
      />
      <div
        className="absolute inset-y-0 bg-amber-700/40"
        style={{ left: "40%", width: "20%" }}
      />
      <div
        className="absolute inset-y-0 bg-emerald-700/40"
        style={{ left: "60%", right: 0 }}
      />
      <div
        className="absolute top-1/2 -translate-y-1/2 size-3 -translate-x-1/2 rounded-full border border-zinc-100 bg-sky-400 shadow"
        style={{ left: `${clamped}%` }}
      />
    </div>
  );
}

function ComponentCell({ label, value }: { label: string; value: number }) {
  const tone = value >= 60 ? "text-emerald-400" : value <= 40 ? "text-red-400" : "text-amber-400";
  return (
    <div className="rounded bg-zinc-900 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={cn("mt-0.5 tabular-nums font-medium", tone)}>{value.toFixed(0)}</div>
    </div>
  );
}
