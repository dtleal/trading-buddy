"use client";

import { Activity } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DashboardTick, IntradayLevels } from "@/lib/types";
import { cn, fmtPrice } from "@/lib/utils";

/**
 * Intraday 5m reference levels per asset. Standard read for 5m analysis:
 * price vs VWAP and the two slow means (EMA200 + SMA200). When the two 200s
 * sit on top of each other (gap small vs ATR) they read as flat → range.
 */
export function IntradayLevelsPanel({ tick }: { tick: DashboardTick | null }) {
  const levels = tick ? Object.values(tick.intraday_levels) : [];
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Activity className="size-4 text-sky-400" />
          <CardTitle>Níveis 5m</CardTitle>
        </div>
        <CardDescription>
          Preço vs VWAP · EMA200 · SMA200 (5m) — 200s coladas e planas = lateral
        </CardDescription>
      </CardHeader>
      <CardContent>
        {levels.length === 0 ? (
          <p className="text-sm text-zinc-500">Sem dados intraday neste tick…</p>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {levels.map((lv) => (
              <LevelCard key={lv.symbol} lv={lv} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LevelCard({ lv }: { lv: IntradayLevels }) {
  const last = lv.last_price;
  // "Coiled": the two 200s within ~10% of the day's ATR → flat/converged.
  const coiled =
    lv.ema_200 !== null &&
    lv.sma_200 !== null &&
    lv.atr_14 !== null &&
    lv.atr_14 > 0 &&
    Math.abs(lv.ema_200 - lv.sma_200) < lv.atr_14 * 0.1;
  const above200 =
    lv.ema_200 !== null && lv.sma_200 !== null && last > lv.ema_200 && last > lv.sma_200;
  const below200 =
    lv.ema_200 !== null && lv.sma_200 !== null && last < lv.ema_200 && last < lv.sma_200;

  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider text-zinc-300">
          {lv.symbol}
        </span>
        {coiled ? (
          <Badge tone="warning">200s coladas · lateral</Badge>
        ) : above200 ? (
          <Badge tone="positive">acima 200s</Badge>
        ) : below200 ? (
          <Badge tone="negative">abaixo 200s</Badge>
        ) : (
          <Badge tone="info">entre as 200s</Badge>
        )}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-zinc-100">{fmtPrice(last)}</div>
      <div className="mt-3 space-y-1 border-t border-zinc-800 pt-2 text-xs">
        <LevelRow label="VWAP" value={lv.vwap} last={last} />
        <LevelRow label="EMA 200" value={lv.ema_200} last={last} />
        <LevelRow label="SMA 200" value={lv.sma_200} last={last} />
      </div>
    </div>
  );
}

function LevelRow({ label, value, last }: { label: string; value: number | null; last: number }) {
  if (value === null) {
    return (
      <div className="flex justify-between text-zinc-600">
        <span>{label}</span>
        <span>n/a</span>
      </div>
    );
  }
  const distPct = ((last - value) / value) * 100;
  const above = last >= value;
  return (
    <div className="flex justify-between">
      <span className="text-zinc-400">{label}</span>
      <span className="flex gap-2 tabular-nums">
        <span className="text-zinc-300">{fmtPrice(value)}</span>
        <span className={cn("w-14 text-right", above ? "text-emerald-400" : "text-red-400")}>
          {distPct >= 0 ? "+" : ""}
          {distPct.toFixed(2)}%
        </span>
      </span>
    </div>
  );
}
