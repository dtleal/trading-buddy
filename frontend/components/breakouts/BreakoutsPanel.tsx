"use client";

import { useMemo, useState } from "react";
import { ArrowDownToLine, ArrowUpFromLine, Zap } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type {
  AssetSymbol as AssetSymbolType,
  Breakout,
  DashboardTick,
  Timeframe as TimeframeType,
} from "@/lib/types";
import { cn } from "@/lib/utils";

const TIMEFRAMES: TimeframeType[] = ["15m", "30m", "60m", "4h"];
const ASSETS: AssetSymbolType[] = ["USTEC", "SPX", "GOLD"];

/**
 * Recent breakouts panel.
 *
 * Shows the last N breakouts emitted by the backend across all monitored
 * timeframes and assets. Filters let the user narrow the view; the underlying
 * data is the same (no API round-trip on filter change). Strength bar gives
 * a quick visual of which breakouts are "fortes" vs marginais.
 */
export function BreakoutsPanel({ tick }: { tick: DashboardTick | null }) {
  const [tfFilter, setTfFilter] = useState<TimeframeType | "all">("all");
  const [assetFilter, setAssetFilter] = useState<AssetSymbolType | "all">("all");

  const breakouts = useMemo(() => {
    const all = tick?.breakouts_recent ?? [];
    return all.filter(
      (b) =>
        (tfFilter === "all" || b.timeframe === tfFilter) &&
        (assetFilter === "all" || b.asset === assetFilter),
    );
  }, [tick, tfFilter, assetFilter]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Zap className="size-4 text-amber-400" />
          <CardTitle>Breakouts</CardTitle>
        </div>
        <CardDescription>
          Donchian (N=20) + expansão de range &gt; 1.3× ATR + squeeze prévio.
          15m · 30m · 60m · 4h.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <FilterChip
            label="todos"
            active={tfFilter === "all"}
            onClick={() => setTfFilter("all")}
          />
          {TIMEFRAMES.map((tf) => (
            <FilterChip
              key={tf}
              label={tf}
              active={tfFilter === tf}
              onClick={() => setTfFilter(tf)}
            />
          ))}
          <span className="text-zinc-700">·</span>
          <FilterChip
            label="todos ativos"
            active={assetFilter === "all"}
            onClick={() => setAssetFilter("all")}
          />
          {ASSETS.map((a) => (
            <FilterChip
              key={a}
              label={a}
              active={assetFilter === a}
              onClick={() => setAssetFilter(a)}
            />
          ))}
        </div>

        {breakouts.length === 0 ? (
          <p className="text-sm italic text-zinc-500">
            Sem breakouts no recorte atual. O detector é estrito por design — em
            mercado lateral pode passar o dia sem disparar.
          </p>
        ) : (
          <ul className="space-y-1.5">
            {breakouts.slice(0, 30).map((b) => (
              <BreakoutRow key={b.id} breakout={b} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      size="sm"
      variant={active ? "default" : "outline"}
      onClick={onClick}
      className="h-6 px-2 text-[11px]"
    >
      {label}
    </Button>
  );
}

function BreakoutRow({ breakout: b }: { breakout: Breakout }) {
  const isUp = b.direction === "up";
  return (
    <li
      className={cn(
        "grid grid-cols-[auto_auto_1fr_auto_auto] items-center gap-3 rounded border bg-zinc-900/30 px-3 py-2 text-sm",
        isUp ? "border-emerald-900/60" : "border-red-900/60",
      )}
    >
      <span className="font-semibold tracking-wider text-zinc-100">{b.asset}</span>
      <Badge tone="neutral">{b.timeframe}</Badge>
      <div className="flex items-center gap-2 text-zinc-200">
        {isUp ? (
          <ArrowUpFromLine className="size-3.5 text-emerald-400" />
        ) : (
          <ArrowDownToLine className="size-3.5 text-red-400" />
        )}
        <span className="tabular-nums">
          {isUp ? "rompeu acima de" : "rompeu abaixo de"}{" "}
          <span className="font-semibold">{b.level.toFixed(2)}</span> @{" "}
          <span className="font-semibold">{b.close.toFixed(2)}</span>
        </span>
        {b.squeeze && <Badge tone="info">squeeze</Badge>}
      </div>
      <StrengthBar value={b.strength} />
      <span className="text-xs tabular-nums text-zinc-500">
        {relativeTime(b.signal_bar_at)}
      </span>
    </li>
  );
}

function StrengthBar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, value));
  const tone = clamped >= 75 ? "bg-red-500" : clamped >= 55 ? "bg-amber-500" : "bg-sky-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-800">
        <div className={cn("h-full transition-all", tone)} style={{ width: `${clamped}%` }} />
      </div>
      <span className="w-7 text-right text-[10px] tabular-nums text-zinc-500">
        {clamped.toFixed(0)}
      </span>
    </div>
  );
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMin = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (diffMin < 1) return "agora";
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  return `${Math.round(diffH / 24)}d`;
}
