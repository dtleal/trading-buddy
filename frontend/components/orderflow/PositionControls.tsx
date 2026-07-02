"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Position } from "@/lib/types";

/**
 * Top-of-card summary for one symbol: the combined floating P&L of every open
 * position, plus the two manual actions — move all positions to breakeven
 * (SL → entry) and close all positions for this asset.
 *
 * Both actions are order sends, so they only appear when the collector permits
 * execution (`executionEnabled`, i.e. allow_auto_close). The P&L number is shown
 * whenever there is a position, gate or not.
 */
export function PositionControls({
  label,
  symbol,
  positions,
  executionEnabled = false,
  onCloseAll,
  onBreakeven,
}: {
  label: string;
  symbol: string;
  positions: Position[];
  executionEnabled?: boolean;
  onCloseAll?: (symbol: string) => Promise<void>;
  onBreakeven?: (symbol: string) => Promise<void>;
}) {
  if (positions.length === 0) return null;

  const total = positions.reduce((sum, p) => sum + p.profit, 0);
  const win = total > 0;
  const flat = total === 0;

  return (
    <div
      className={cn(
        "rounded-md border px-2 py-2",
        win
          ? "border-emerald-700/60 bg-emerald-950/20"
          : flat
            ? "border-zinc-700/60 bg-zinc-900/50"
            : "border-rose-700/60 bg-rose-950/20",
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
          P&L · {label}
        </span>
        <span
          className={cn(
            "text-base font-bold tabular-nums",
            win ? "text-emerald-400" : flat ? "text-zinc-300" : "text-rose-400",
          )}
        >
          {total >= 0 ? "+" : "−"}
          {Math.abs(total).toFixed(2)}
        </span>
      </div>

      {executionEnabled && onBreakeven && onCloseAll && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <ConfirmButton
            idle={`Breakeven`}
            armed={`Confirmar BE?`}
            busy="Movendo…"
            tone="amber"
            onConfirm={() => onBreakeven(symbol)}
          />
          <ConfirmButton
            idle={`Fechar tudo`}
            armed={`Confirmar?`}
            busy="Fechando…"
            tone="rose"
            onConfirm={() => onCloseAll(symbol)}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Action button with a 2-click guard: the first click arms it for a few seconds
 * ("Confirmar?"), the second executes. Fast enough to react to an alert, but a
 * stray single click never touches real orders.
 */
function ConfirmButton({
  idle,
  armed: armedLabel,
  busy: busyLabel,
  tone,
  onConfirm,
}: {
  idle: string;
  armed: string;
  busy: string;
  tone: "rose" | "amber";
  onConfirm: () => Promise<void>;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    if (!armed) {
      setArmed(true);
      setError(null);
      setTimeout(() => setArmed(false), 3000);
      return;
    }
    setBusy(true);
    try {
      await onConfirm();
      setArmed(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha.");
    } finally {
      setBusy(false);
    }
  }

  const palette =
    tone === "rose"
      ? {
          idle: "bg-rose-500/15 text-rose-300 hover:bg-rose-500/25",
          armed: "animate-pulse bg-rose-600 text-white hover:bg-rose-500",
        }
      : {
          idle: "bg-amber-500/15 text-amber-300 hover:bg-amber-500/25",
          armed: "animate-pulse bg-amber-600 text-white hover:bg-amber-500",
        };

  return (
    <div>
      <button
        onClick={handleClick}
        disabled={busy}
        className={cn(
          "w-full rounded px-2 py-1.5 text-[11px] font-bold uppercase tracking-wider transition-colors disabled:opacity-50",
          armed ? palette.armed : palette.idle,
        )}
      >
        {busy ? busyLabel : armed ? armedLabel : idle}
      </button>
      {error && <div className="mt-1 text-[10px] text-rose-400">{error}</div>}
    </div>
  );
}
