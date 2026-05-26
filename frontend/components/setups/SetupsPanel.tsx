"use client";

import { Target, TrendingDown, TrendingUp } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DashboardTick, TradeSetup } from "@/lib/types";
import { cn, fmtPrice } from "@/lib/utils";

/**
 * Trade setup panel. Mirrors the CLI's 🎯 "Setup com vantagem" — only renders
 * setup cards when the detector emits one. Stays explicitly silent (with a
 * dim explainer) otherwise. No suggestion if no confluence.
 */
export function SetupsPanel({ tick }: { tick: DashboardTick | null }) {
  const setups = tick?.setups ?? [];
  return (
    <Card className="border-amber-900/40">
      <CardHeader>
        <div className="flex items-center gap-2">
          <Target className="size-4 text-amber-400" />
          <CardTitle>Setup com vantagem</CardTitle>
        </div>
        <CardDescription>
          Confluência objetiva: score estrutural + EMA200 + SMA200 + VWAP + pullback + R:R ≥ 2
        </CardDescription>
      </CardHeader>
      <CardContent>
        {setups.length === 0 ? (
          <p className="text-sm italic text-zinc-500">
            Sem setup com vantagem clara agora — mercado em LATERAL ou sem confluência.
          </p>
        ) : (
          <div className="space-y-4">
            {setups.map((setup) => (
              <SetupCard key={`${setup.asset}-${setup.direction}`} setup={setup} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SetupCard({ setup }: { setup: TradeSetup }) {
  const isLong = setup.direction === "LONG";
  return (
    <div
      className={cn(
        "rounded-md border bg-zinc-900/40 p-4",
        isLong ? "border-emerald-900/60" : "border-red-900/60",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold tracking-wider text-zinc-100">{setup.asset}</span>
          {isLong ? (
            <Badge tone="positive">
              <TrendingUp className="mr-1 size-3" /> COMPRA
            </Badge>
          ) : (
            <Badge tone="negative">
              <TrendingDown className="mr-1 size-3" /> VENDA
            </Badge>
          )}
        </div>
        <div className="text-sm text-zinc-400">
          R:R <span className="font-semibold tabular-nums text-zinc-100">{setup.risk_reward.toFixed(2)}</span>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
        <Cell label="Entry zone" tone="info">
          {fmtPrice(setup.entry_zone_low)} – {fmtPrice(setup.entry_zone_high)}
        </Cell>
        <Cell label="Stop" tone="negative">
          {fmtPrice(setup.stop_level)}
        </Cell>
        <Cell label="Alvo" tone="positive">
          {fmtPrice(setup.target_level)}
        </Cell>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
        <Badge>{setup.trend_label}</Badge>
        <Badge tone="info">{setup.continuation_label}</Badge>
      </div>

      <ul className="mt-3 space-y-1 text-xs text-zinc-400">
        {setup.rationale.map((r, i) => (
          <li key={i} className="flex gap-2">
            <span className="mt-1 size-1 shrink-0 rounded-full bg-zinc-600" />
            <span>{r}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Cell({
  label,
  tone,
  children,
}: {
  label: string;
  tone: "info" | "positive" | "negative";
  children: React.ReactNode;
}) {
  const toneClass =
    tone === "positive"
      ? "text-emerald-400"
      : tone === "negative"
        ? "text-red-400"
        : "text-sky-400";
  return (
    <div className="rounded bg-zinc-900 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={cn("mt-0.5 tabular-nums font-semibold", toneClass)}>{children}</div>
    </div>
  );
}
