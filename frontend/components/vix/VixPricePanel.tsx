"use client";

import { ArrowDownRight, ArrowUpRight, PauseCircle, MinusCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DashboardTick, VixPriceSignal } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * "VIX × Preço (5m)" — the per-asset stance from correlating the VIX's 5m path
 * with each asset's 5m tape (trend quality + Bollinger position). One tile per
 * asset: the standing playbook (sell rallies / buy dips / stay out), a pulsing
 * "zona AGORA" marker when price is at the actionable band, and a caution
 * badge when a divergence argues for closing open positions.
 * Silent (renders nothing) until the first tick carries signals.
 */
export function VixPricePanel({ tick }: { tick: DashboardTick | null }) {
  const signals = Object.values(tick?.vix_price ?? {});
  if (signals.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>VIX × Preço (5m)</CardTitle>
        <CardDescription>
          Postura por ativo: direção do VIX cruzada com a tendência e as bandas de Bollinger do 5m
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {signals.map((sig) => (
            <StanceTile key={sig.asset} sig={sig} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function StanceTile({ sig }: { sig: VixPriceSignal }) {
  const s = STANCE_STYLE[sig.stance];
  const Icon = s.icon;

  return (
    <div className={cn("rounded-lg border border-zinc-800 p-3 space-y-2", s.bg)}>
      <div className="flex flex-wrap items-center gap-2">
        <Icon className={cn("size-4 shrink-0", s.icon_color)} />
        <span className="text-sm font-semibold text-zinc-100">{sig.asset}</span>
        <Badge tone={s.tone}>{s.label}</Badge>
        {sig.trigger && (
          <span className="flex items-center gap-1 text-[11px] font-bold uppercase tracking-wide text-amber-300">
            <span className="size-2 animate-pulse rounded-full bg-amber-400" />
            zona agora
          </span>
        )}
      </div>

      {sig.caution && (
        <Badge tone="warning">{CAUTION_LABEL[sig.caution]}</Badge>
      )}

      <p className="text-xs leading-snug text-zinc-300">{sig.headline}</p>

      <ul className="space-y-0.5 text-[11px] text-zinc-500">
        {sig.rationale.map((r, i) => (
          <li key={i}>· {r}</li>
        ))}
      </ul>
    </div>
  );
}

const CAUTION_LABEL: Record<NonNullable<VixPriceSignal["caution"]>, string> = {
  exit_longs: "ENCERRAR COMPRAS",
  exit_shorts: "ENCERRAR VENDAS",
};

const STANCE_STYLE: Record<
  VixPriceSignal["stance"],
  {
    label: string;
    tone: "positive" | "negative" | "warning" | "neutral";
    icon: typeof ArrowDownRight;
    icon_color: string;
    bg: string;
  }
> = {
  sell_rallies: {
    label: "VENDER REPIQUE",
    tone: "negative",
    icon: ArrowDownRight,
    icon_color: "text-red-400",
    bg: "bg-red-950/20",
  },
  buy_dips: {
    label: "COMPRAR RECUO",
    tone: "positive",
    icon: ArrowUpRight,
    icon_color: "text-emerald-400",
    bg: "bg-emerald-950/20",
  },
  stay_out: {
    label: "FICAR DE FORA",
    tone: "warning",
    icon: PauseCircle,
    icon_color: "text-amber-400",
    bg: "bg-amber-950/10",
  },
  neutral: {
    label: "NEUTRO",
    tone: "neutral",
    icon: MinusCircle,
    icon_color: "text-zinc-500",
    bg: "",
  },
};
