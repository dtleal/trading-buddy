"use client";

import { useMemo, useState } from "react";
import { ArrowDownToLine, ArrowUpFromLine, History, Zap } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TRACKED_ASSETS } from "@/lib/types";
import type {
  AssetSymbol as AssetSymbolType,
  Breakout,
  DashboardTick,
  Timeframe as TimeframeType,
} from "@/lib/types";
import { cn, fmtPrice, priceDigits } from "@/lib/utils";

const TIMEFRAMES: TimeframeType[] = ["5m", "15m", "30m", "60m", "4h"];
const ASSETS: AssetSymbolType[] = TRACKED_ASSETS.map((a) => a.key);

// Breakouts older than this are stale for a day-trader — they don't open a new
// decision window. Hidden by default; revealed via the "histórico" toggle.
const ACTIONABLE_MINUTES = 60;

/**
 * Breakouts panel — built around "what's actionable RIGHT NOW".
 *
 * Default view shows only signals < ACTIONABLE_MINUTES old. The user can
 * include older ones via the "histórico" toggle; those render dim + strike
 * so they read as reference, not as call-to-action.
 */
export function BreakoutsPanel({ tick }: { tick: DashboardTick | null }) {
  const [tfFilter, setTfFilter] = useState<TimeframeType | "all">("all");
  const [assetFilter, setAssetFilter] = useState<AssetSymbolType | "all">("all");
  const [showHistory, setShowHistory] = useState(false);

  const { actionable, history } = useMemo(() => {
    const all = tick?.breakouts_recent ?? [];
    const now = Date.now();
    const cutoff = now - ACTIONABLE_MINUTES * 60_000;
    const filtered = all.filter(
      (b) =>
        (tfFilter === "all" || b.timeframe === tfFilter) &&
        (assetFilter === "all" || b.asset === assetFilter),
    );
    const actionable = filtered.filter(
      (b) => new Date(b.signal_bar_at).getTime() >= cutoff,
    );
    const history = filtered.filter(
      (b) => new Date(b.signal_bar_at).getTime() < cutoff,
    );
    return { actionable, history };
  }, [tick, tfFilter, assetFilter]);

  const visible = showHistory ? [...actionable, ...history] : actionable;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Zap className="size-4 text-amber-400" />
          <CardTitle>Breakouts acionáveis</CardTitle>
        </div>
        <CardDescription>
          Apenas sinais dos últimos {ACTIONABLE_MINUTES}min — janela de decisão
          de day-trade. Filtros + toggle pra ver histórico mais velho.
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

        {actionable.length === 0 && !showHistory ? (
          <EmptyState olderCount={history.length} onShowHistory={() => setShowHistory(true)} />
        ) : (
          <>
            <ul className="space-y-1.5">
              {visible.slice(0, 30).map((b) => {
                const stale = new Date(b.signal_bar_at).getTime() < Date.now() - ACTIONABLE_MINUTES * 60_000;
                return <BreakoutRow key={b.id} breakout={b} stale={stale} />;
              })}
            </ul>
            {history.length > 0 && (
              <div className="flex justify-center pt-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowHistory((v) => !v)}
                  className="text-xs text-zinc-500 hover:text-zinc-300"
                >
                  <History className="mr-1.5 size-3.5" />
                  {showHistory
                    ? `ocultar histórico (${history.length})`
                    : `mostrar histórico (${history.length} sinais > ${ACTIONABLE_MINUTES}min)`}
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyState({
  olderCount,
  onShowHistory,
}: {
  olderCount: number;
  onShowHistory: () => void;
}) {
  return (
    <div className="rounded border border-dashed border-zinc-800 bg-zinc-900/30 p-4 text-center">
      <p className="text-sm text-zinc-400">
        Sem breakouts acionáveis nos últimos {ACTIONABLE_MINUTES}min.
      </p>
      <p className="mt-1 text-xs italic text-zinc-500">
        Mercado em consolidação ou aguardando próximo movimento. Quando vier um
        sinal real, vai aparecer aqui e disparar push no celular em &lt;5min.
      </p>
      {olderCount > 0 && (
        <Button
          variant="ghost"
          size="sm"
          onClick={onShowHistory}
          className="mt-2 text-xs text-zinc-500 hover:text-zinc-300"
        >
          <History className="mr-1.5 size-3.5" />
          mostrar histórico ({olderCount} sinais &gt; {ACTIONABLE_MINUTES}min)
        </Button>
      )}
    </div>
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

function BreakoutRow({ breakout: b, stale }: { breakout: Breakout; stale: boolean }) {
  const isUp = b.direction === "up";
  return (
    <li
      className={cn(
        "grid grid-cols-[auto_auto_1fr_auto_auto] items-center gap-3 rounded border px-3 py-2 text-sm transition-opacity",
        isUp ? "border-emerald-900/60" : "border-red-900/60",
        stale
          ? "bg-zinc-950/30 opacity-50 [&_*]:line-through [&_.no-strike]:no-underline"
          : "bg-zinc-900/30",
      )}
    >
      <span className="font-semibold tracking-wider text-zinc-100 no-strike">{b.asset}</span>
      <Badge tone="neutral">{b.timeframe}</Badge>
      <div className="flex items-center gap-2 text-zinc-200">
        {isUp ? (
          <ArrowUpFromLine className="size-3.5 text-emerald-400 no-strike" />
        ) : (
          <ArrowDownToLine className="size-3.5 text-red-400 no-strike" />
        )}
        <span className="tabular-nums">
          {isUp ? "rompeu acima de" : "rompeu abaixo de"}{" "}
          <span className="font-semibold">{fmtPrice(b.level, priceDigits(b.close))}</span> @{" "}
          <span className="font-semibold">{fmtPrice(b.close)}</span>
        </span>
        {b.squeeze && (
          <Badge tone="info" className="no-strike">
            squeeze
          </Badge>
        )}
        {stale && (
          <Badge tone="neutral" className="no-strike">
            histórico
          </Badge>
        )}
      </div>
      <StrengthBar value={b.strength} />
      <span className="text-xs tabular-nums text-zinc-500 no-strike">
        {relativeTime(b.signal_bar_at)}
      </span>
    </li>
  );
}

function StrengthBar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, value));
  const tone = clamped >= 75 ? "bg-red-500" : clamped >= 55 ? "bg-amber-500" : "bg-sky-500";
  return (
    <div className="flex items-center gap-2 no-strike">
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
