"use client";

import { Card, CardContent } from "@/components/ui/card";
import { PRESETS } from "@/lib/performance";
import { cn } from "@/lib/utils";
import type { PerformanceQuery } from "@/lib/types";

/**
 * The filter bar: a ready-made window (today / week / month / ...), an
 * optional exact date range, which assets to count and whether to look at
 * hand-placed trades, the bot's, or both.
 *
 * A date range always wins over the preset — same rule the backend applies —
 * so picking dates greys the preset row out.
 */
export function PerformanceFilterBar({
  query,
  onChange,
  availableSymbols,
}: {
  query: PerformanceQuery;
  onChange: (next: PerformanceQuery) => void;
  availableSymbols: string[];
}) {
  const customRange = Boolean(query.start || query.end);
  const symbols = query.symbols ?? [];

  const toggleSymbol = (symbol: string) => {
    const next = symbols.includes(symbol)
      ? symbols.filter((s) => s !== symbol)
      : [...symbols, symbol];
    onChange({ ...query, symbols: next });
  };

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-4">
        {/* Ready-made windows */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-16 text-xs uppercase tracking-wider text-zinc-500">
            Período
          </span>
          {PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() =>
                onChange({ ...query, preset: preset.key, start: undefined, end: undefined })
              }
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                !customRange && query.preset === preset.key
                  ? "bg-sky-900 text-sky-200 ring-1 ring-sky-700/60"
                  : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
                customRange && "opacity-40",
              )}
            >
              {preset.label}
            </button>
          ))}
        </div>

        {/* Exact range */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-16 text-xs uppercase tracking-wider text-zinc-500">
            Datas
          </span>
          <input
            type="date"
            value={query.start ?? ""}
            onChange={(e) => onChange({ ...query, start: e.target.value || undefined })}
            className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1 text-xs text-zinc-200"
          />
          <span className="text-xs text-zinc-500">até</span>
          <input
            type="date"
            value={query.end ?? ""}
            onChange={(e) => onChange({ ...query, end: e.target.value || undefined })}
            className="rounded-md border border-zinc-800 bg-zinc-900 px-2 py-1 text-xs text-zinc-200"
          />
          {customRange && (
            <button
              type="button"
              onClick={() => onChange({ ...query, start: undefined, end: undefined })}
              className="rounded-md bg-zinc-900 px-2.5 py-1 text-xs text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            >
              limpar datas
            </button>
          )}
        </div>

        {/* Assets */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-16 text-xs uppercase tracking-wider text-zinc-500">
            Ativos
          </span>
          <button
            type="button"
            onClick={() => onChange({ ...query, symbols: [] })}
            className={cn(
              "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
              symbols.length === 0
                ? "bg-sky-900 text-sky-200 ring-1 ring-sky-700/60"
                : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
            )}
          >
            Todos
          </button>
          {availableSymbols.map((symbol) => (
            <button
              key={symbol}
              type="button"
              onClick={() => toggleSymbol(symbol)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                symbols.includes(symbol)
                  ? "bg-sky-900 text-sky-200 ring-1 ring-sky-700/60"
                  : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
              )}
            >
              {symbol}
            </button>
          ))}
          {availableSymbols.length === 0 && (
            <span className="text-xs text-zinc-600">sem histórico ainda</span>
          )}
        </div>

        {/* Origin */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="w-16 text-xs uppercase tracking-wider text-zinc-500">
            Origem
          </span>
          {(
            [
              { key: "all", label: "Tudo" },
              { key: "manual", label: "Manual" },
              { key: "bot", label: "Bot scalper" },
            ] as const
          ).map((option) => (
            <button
              key={option.key}
              type="button"
              onClick={() => onChange({ ...query, source: option.key })}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                (query.source ?? "all") === option.key
                  ? "bg-sky-900 text-sky-200 ring-1 ring-sky-700/60"
                  : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
