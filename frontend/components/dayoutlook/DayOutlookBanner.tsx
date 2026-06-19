"use client";

import { AlertTriangle, Gauge, Rocket } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DashboardTick, DayOutlook, DayRegime } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * "Perfil do Dia" banner — the movement-potential / liquidity gate.
 *
 * Answers the one question the trader asks at the open: does today promise
 * real movement, or is it a thin/chop trap (holiday, no catalyst, collapsing
 * volume)? Renders prominently at the top of the dashboard, colored by regime.
 * Silent (renders nothing) until the first tick carries an outlook.
 */
export function DayOutlookBanner({ tick }: { tick: DashboardTick | null }) {
  const outlook = tick?.day_outlook ?? null;
  if (!outlook) return null;

  const s = STYLE[outlook.regime];
  const Icon = s.icon;

  return (
    <Card className={cn("border-l-4", s.card)}>
      <CardContent className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start sm:gap-5">
        <div className="flex items-center gap-3 sm:flex-col sm:items-center sm:gap-1">
          <Icon className={cn("size-9 shrink-0", s.icon_color)} />
          <div className="flex items-baseline gap-1">
            <span className={cn("text-4xl font-bold tabular-nums", s.score_color)}>
              {Math.round(outlook.score)}
            </span>
            <span className="text-xs text-zinc-500">/100</span>
          </div>
        </div>

        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("text-xs font-semibold uppercase tracking-widest", s.label_color)}>
              Perfil do Dia
            </span>
            <Badge tone={s.tone}>{s.label}</Badge>
            {outlook.is_us_holiday && <Badge tone="warning">Feriado EUA</Badge>}
            {outlook.high_impact_count > 0 && (
              <Badge tone="info">
                {outlook.high_impact_count} evento(s) de alto impacto
              </Badge>
            )}
            {outlook.liquidity_ratio != null && (
              <Badge tone={outlook.liquidity_ratio < 0.75 ? "warning" : "neutral"}>
                Volume MT5: {Math.round(outlook.liquidity_ratio * 100)}% do normal
              </Badge>
            )}
          </div>

          <p className={cn("text-base font-semibold leading-snug", s.headline_color)}>
            {outlook.headline}
          </p>

          {outlook.rationale.length > 0 && (
            <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-400">
              {outlook.rationale.map((r, i) => (
                <li key={i} className="flex items-center gap-1">
                  <span className="text-zinc-600">·</span>
                  {r}
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

const STYLE: Record<
  DayRegime,
  {
    label: string;
    tone: "positive" | "negative" | "warning" | "neutral";
    card: string;
    icon: typeof Gauge;
    icon_color: string;
    score_color: string;
    headline_color: string;
    label_color: string;
  }
> = {
  thin: {
    label: "DIA FRACO",
    tone: "warning",
    card: "border-l-amber-500 bg-amber-950/20",
    icon: AlertTriangle,
    icon_color: "text-amber-400",
    score_color: "text-amber-300",
    headline_color: "text-amber-200",
    label_color: "text-amber-500/80",
  },
  normal: {
    label: "DIA NORMAL",
    tone: "neutral",
    card: "border-l-zinc-600",
    icon: Gauge,
    icon_color: "text-zinc-400",
    score_color: "text-zinc-200",
    headline_color: "text-zinc-300",
    label_color: "text-zinc-500",
  },
  expansion: {
    label: "DIA DE EXPANSÃO",
    tone: "positive",
    card: "border-l-emerald-500 bg-emerald-950/20",
    icon: Rocket,
    icon_color: "text-emerald-400",
    score_color: "text-emerald-300",
    headline_color: "text-emerald-200",
    label_color: "text-emerald-500/80",
  },
};
