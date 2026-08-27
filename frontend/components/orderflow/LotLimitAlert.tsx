"use client";

import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DEFAULT_LOT_LIMITS } from "@/lib/lotLimits";
import { TRACKED_ASSETS, type AssetSymbol } from "@/lib/types";

/** Lots with up to 2 decimals and no trailing zeros (40, 12.5, 0.01). */
function formatLots(lots: number): string {
  return lots.toFixed(2).replace(/\.?0+$/, "");
}

/**
 * Open-volume alert that sits next to the asset name. It shows how many lots
 * are open right now against the per-asset cap; when the cap is reached the
 * badge turns red and blinks so it is impossible to miss while scanning the
 * strip. Hidden while the asset is flat — six "0 / 40" chips would be noise.
 */
export function LotLimitBadge({ lots, limit }: { lots: number; limit: number }) {
  if (lots <= 0) return null;
  const over = lots >= limit;

  return (
    <span
      title={`${formatLots(lots)} lotes abertos · limite ${formatLots(limit)}`}
      className={cn(
        "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold tabular-nums",
        over
          ? "animate-pulse bg-rose-600 text-white ring-2 ring-rose-300 shadow-[0_0_10px_rgba(244,63,94,0.9)]"
          : "bg-zinc-800 text-zinc-300 ring-1 ring-zinc-700",
      )}
    >
      {formatLots(lots)}/{formatLots(limit)}
    </span>
  );
}

/**
 * The settings panel behind the header button: one number box per asset. Each
 * edit is saved right away (localStorage), so there is no "save" step — only a
 * reset back to the defaults.
 */
export function LotLimitSettings({
  limits,
  setLimit,
  resetLimits,
  onClose,
}: {
  limits: Record<string, number>;
  setLimit: (symbol: AssetSymbol, lots: number) => void;
  resetLimits: () => void;
  onClose: () => void;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-zinc-200">
            Limite de lotes abertos
          </div>
          <div className="text-[11px] text-zinc-500">
            O selo ao lado do ativo pisca em vermelho quando o volume aberto chega no limite.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={resetLimits}>
            Padrão
          </Button>
          <Button variant="outline" size="sm" onClick={onClose}>
            Fechar
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {TRACKED_ASSETS.map((a) => (
          <label key={a.key} className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
              {a.label}
            </span>
            <input
              type="number"
              min={0.01}
              step={0.01}
              value={limits[a.key] ?? DEFAULT_LOT_LIMITS[a.key] ?? 1}
              onChange={(e) => {
                const next = Number(e.target.value);
                if (Number.isFinite(next) && next > 0) setLimit(a.key, next);
              }}
              className="w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm tabular-nums text-zinc-100 outline-none focus:border-zinc-500"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

/** Header button that opens/closes the settings panel above the strip. */
export function LotLimitSettingsButton({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <Button variant={on ? "default" : "outline"} size="sm" onClick={onToggle} aria-pressed={on}>
      <Settings2 className="mr-1 size-3.5" />
      Limite de lotes
    </Button>
  );
}
