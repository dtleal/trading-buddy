"use client";

import { useState } from "react";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AutoCloseStatus } from "@/lib/types";

/**
 * Whole-account profit-target auto-close control.
 *
 * Set a USD target and ARM; when the summed floating P&L of ALL open positions
 * reaches it, the backend tells the collector to close everything (one-shot).
 * DESARMAR is the always-available kill switch. The controls are inert unless
 * the collector opted into execution (`allow_auto_close`), and the panel says
 * so, so it's never a mystery why nothing fires.
 */
export function AutoCloseControl({
  status,
  arm,
  disarm,
}: {
  status: AutoCloseStatus | null;
  arm: (targetUsd: number) => Promise<void>;
  disarm: () => Promise<void>;
}) {
  const [target, setTarget] = useState("35");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!status) return null;

  const profit = status.open_profit;
  const profitTone = profit > 0 ? "text-emerald-400" : profit < 0 ? "text-rose-400" : "text-zinc-400";

  async function onArm() {
    const value = Number(target);
    if (!Number.isFinite(value) || value <= 0) {
      setError("Alvo deve ser um número positivo.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await arm(value);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao armar.");
    } finally {
      setBusy(false);
    }
  }

  async function onDisarm() {
    setBusy(true);
    try {
      await disarm();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao desarmar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2",
        status.armed ? "border-amber-600/60 bg-amber-950/20" : "border-zinc-800 bg-zinc-950/40",
      )}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          {status.armed ? (
            <ShieldAlert className="size-4 animate-pulse text-amber-400" />
          ) : (
            <ShieldCheck className="size-4 text-zinc-500" />
          )}
          <div className="text-sm font-semibold text-zinc-200">
            Auto-close da conta
            <span className="ml-2 text-[11px] font-normal text-zinc-500">
              P&L aberto:{" "}
              <span className={cn("tabular-nums font-semibold", profitTone)}>
                {profit >= 0 ? "+" : "−"}
                {Math.abs(profit).toFixed(2)}
              </span>
            </span>
          </div>
        </div>

        {!status.enabled ? (
          <span className="text-[11px] text-zinc-500">
            execução desabilitada — ligue <code className="text-zinc-400">allow_auto_close</code> no
            collector
          </span>
        ) : status.armed ? (
          <div className="flex items-center gap-2">
            <span className="rounded bg-amber-500/20 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-amber-300">
              ARMADO @ ${status.target_usd?.toFixed(2)}
            </span>
            <button
              onClick={onDisarm}
              disabled={busy}
              className="rounded bg-zinc-700 px-2.5 py-1 text-[11px] font-semibold text-zinc-100 hover:bg-zinc-600 disabled:opacity-50"
            >
              DESARMAR
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <div className="flex items-center rounded border border-zinc-700 bg-zinc-900">
              <span className="pl-2 text-[11px] text-zinc-500">$</span>
              <input
                type="number"
                inputMode="decimal"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className="w-20 bg-transparent px-1 py-1 text-[12px] tabular-nums text-zinc-100 outline-none"
                placeholder="35"
              />
            </div>
            <button
              onClick={onArm}
              disabled={busy}
              className="rounded bg-amber-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-amber-500 disabled:opacity-50"
            >
              ARMAR
            </button>
          </div>
        )}
      </div>

      {(error || status.last_result) && (
        <div className={cn("mt-1.5 text-[10px]", error ? "text-rose-400" : "text-zinc-500")}>
          {error ?? status.last_result}
        </div>
      )}
    </div>
  );
}
