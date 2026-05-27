"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type {
  BiasLevel,
  BiasReport,
  DashboardTick,
  IntradayBiasReport,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Dual-lens bias panel:
 * - 🏛 Structural (daily) — score from the existing combined bias use case
 *   (technical 40% + macro 30% + sentiment 30%). Anchored on MA200d.
 * - ⚡ Intraday (5m) — score derived from price position vs VWAP / EMA200 /
 *   SMA200 / EMA20 / EMA9 on the 5m timeframe.
 *
 * Convergence flag (✅ / ⚠️) makes the all-too-common "daily ALTA but 5m
 * BAIXA" divergence impossible to miss.
 */
export function BiasPanel({ tick }: { tick: DashboardTick | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Viés por ativo (dual-lens)</CardTitle>
        <CardDescription>
          🏛 estrutural (MA200d + macro) vs ⚡ intraday (5m). Quando divergem,
          o tape do 5m manda.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {tick ? (
          <div className="space-y-3">
            {Object.values(tick.bias).map((report) => {
              const intraday = tick.intraday_bias?.[report.asset] ?? null;
              return <BiasRow key={report.asset} structural={report} intraday={intraday} />;
            })}
          </div>
        ) : (
          <p className="text-sm text-zinc-500">Aguardando primeiro tick…</p>
        )}
      </CardContent>
    </Card>
  );
}

function BiasRow({
  structural,
  intraday,
}: {
  structural: BiasReport;
  intraday: IntradayBiasReport | null;
}) {
  const { asset, score, level, components } = structural;
  const divergence = intraday !== null && intraday.level !== level && level !== "neutral" && intraday.level !== "neutral";
  const intradayDelta = intraday !== null ? intraday.score - score : null;

  return (
    <div
      className={cn(
        "rounded-md border p-3",
        divergence ? "border-amber-700/60 bg-amber-950/20" : "border-zinc-800 bg-zinc-900/40",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-semibold tracking-wider text-zinc-100">{asset}</span>
        {divergence && <Badge tone="warning">⚠ Diverge</Badge>}
        {!divergence && intraday !== null && <Badge tone="positive">✓ Alinhado</Badge>}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <LensCard
          icon="🏛"
          label="Estrutural (diário)"
          score={score}
          level={level}
        />
        {intraday ? (
          <LensCard
            icon="⚡"
            label="Intraday (5m)"
            score={intraday.score}
            level={intraday.level}
            delta={intradayDelta}
          />
        ) : (
          <div className="rounded bg-zinc-900 px-3 py-2 text-xs text-zinc-500">
            ⚡ Intraday: aguardando dados 5m
          </div>
        )}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <ComponentCell label="Técnico" value={components.technical} />
        <ComponentCell label="Macro" value={components.macro} />
        <ComponentCell label="Sentim." value={components.sentiment} />
      </div>

      {intraday && intraday.signals.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-zinc-500 hover:text-zinc-300">
            5m signals →
          </summary>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {intraday.signals.map((s, i) => (
              <span
                key={i}
                className={cn(
                  "rounded px-1.5 py-0.5",
                  s.startsWith("acima") && "bg-emerald-950 text-emerald-300",
                  s.startsWith("abaixo") && "bg-red-950 text-red-300",
                  s.startsWith("em") && "bg-zinc-800 text-zinc-300",
                  s.includes("indisponível") && "bg-zinc-900 text-zinc-500 italic",
                )}
              >
                {s}
              </span>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function LensCard({
  icon,
  label,
  score,
  level,
  delta,
}: {
  icon: string;
  label: string;
  score: number;
  level: BiasLevel;
  delta?: number | null;
}) {
  return (
    <div className="rounded bg-zinc-900 px-3 py-2">
      <div className="flex items-center justify-between gap-2 text-[10px] uppercase tracking-wider text-zinc-500">
        <span>
          {icon} {label}
        </span>
        {delta !== null && delta !== undefined && (
          <span
            className={cn(
              "tabular-nums",
              delta > 5 ? "text-emerald-400" : delta < -5 ? "text-red-400" : "text-zinc-500",
            )}
          >
            {delta > 0 ? "+" : ""}
            {delta.toFixed(0)}
          </span>
        )}
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">{score.toFixed(0)}</span>
        <BiasBadge level={level} />
      </div>
      <ScoreBar value={score} />
    </div>
  );
}

function BiasBadge({ level }: { level: BiasLevel }) {
  if (level === "bullish") return <Badge tone="positive">ALTA</Badge>;
  if (level === "bearish") return <Badge tone="negative">BAIXA</Badge>;
  return <Badge tone="warning">LATERAL</Badge>;
}

function ScoreBar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className="mt-2 relative h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
      <div className="absolute inset-y-0 left-0 bg-red-700/40" style={{ width: "40%" }} />
      <div className="absolute inset-y-0 bg-amber-700/40" style={{ left: "40%", width: "20%" }} />
      <div className="absolute inset-y-0 bg-emerald-700/40" style={{ left: "60%", right: 0 }} />
      <div
        className="absolute top-1/2 -translate-y-1/2 size-2.5 -translate-x-1/2 rounded-full border border-zinc-100 bg-sky-400 shadow"
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
