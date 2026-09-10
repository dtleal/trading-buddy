"use client";

import { useEffect, useState } from "react";
import { Lock, LockOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AutoBreakevenStatus } from "@/lib/types";

/**
 * Per-position auto-breakeven control.
 *
 * Set a USD amount and ARM: the instant ANY open position's floating profit
 * reaches it, the backend tells the collector to move that position's stop to
 * its entry price, so the trade can no longer come back and lose. It is per
 * position (not per account) and it stays armed, protecting each new trade as
 * it crosses. Inert unless the collector opted into execution
 * (`allow_auto_close`) — moving a stop is still an order sent to the broker.
 */
export function AutoBreakevenControl({
  status,
  arm,
  disarm,
}: {
  status: AutoBreakevenStatus | null;
  arm: (thresholdUsd: number) => Promise<void>;
  disarm: () => Promise<void>;
}) {
  const [threshold, setThreshold] = useState("6");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Show the armed value in the box, so re-arming starts from what is running
  // instead of the default. Only while idle — never fight the user's typing.
  const armedAt = status?.threshold_usd ?? null;
  useEffect(() => {
    if (armedAt != null) setThreshold(String(armedAt));
  }, [armedAt]);

  if (!status) return null;

  async function onArm() {
    const value = Number(threshold);
    if (!Number.isFinite(value) || value <= 0) {
      setError("Valor deve ser um número positivo.");
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
        status.armed ? "border-sky-600/60 bg-sky-950/20" : "border-zinc-800 bg-zinc-950/40",
      )}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          {status.armed ? (
            <Lock className="size-4 text-sky-400" />
          ) : (
            <LockOpen className="size-4 text-zinc-500" />
          )}
          <div className="text-sm font-semibold text-zinc-200">
            Stop no zero a zero (por ordem)
            <span className="ml-2 text-[11px] font-normal text-zinc-500">
              {status.open_positions === 0
                ? "nenhuma ordem aberta"
                : `${status.protected} de ${status.open_positions} protegida(s)`}
            </span>
          </div>
        </div>

        {!status.enabled ? (
          <span className="text-[11px] text-zinc-500">
            execução desabilitada — ligue <code className="text-zinc-400">allow_auto_close</code> no
            collector
          </span>
        ) : (
          <div className="flex items-center gap-2">
            {status.armed && (
              <span className="rounded bg-sky-500/20 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-sky-300">
                ARMADO @ ${status.threshold_usd?.toFixed(2)}
              </span>
            )}
            <div className="flex items-center rounded border border-zinc-700 bg-zinc-900">
              <span className="pl-2 text-[11px] text-zinc-500">$</span>
              <input
                type="number"
                inputMode="decimal"
                value={threshold}
                onChange={(e) => setThreshold(e.target.value)}
                className="w-20 bg-transparent px-1 py-1 text-[12px] tabular-nums text-zinc-100 outline-none"
                placeholder="6"
              />
            </div>
            <button
              onClick={onArm}
              disabled={busy}
              className="rounded bg-sky-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-sky-500 disabled:opacity-50"
            >
              {status.armed ? "SALVAR" : "ARMAR"}
            </button>
            {status.armed && (
              <button
                onClick={onDisarm}
                disabled={busy}
                className="rounded bg-zinc-700 px-2.5 py-1 text-[11px] font-semibold text-zinc-100 hover:bg-zinc-600 disabled:opacity-50"
              >
                DESARMAR
              </button>
            )}
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
