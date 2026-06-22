"use client";

import { useState } from "react";
import { Bot, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BotStatus } from "@/lib/types";

/**
 * Explosion-scalper bot control. This is the only thing that OPENS positions
 * (demo only), so it's visually loud and the controls are inert unless the
 * collector permits auto-trade on a demo account.
 *
 * Entries: opens on detected bursts (size per symbol: index 2.0 / gold 0.12 lt),
 * up to 6 per symbol. Exit: closes the whole account at +profit_target, or at
 * −loss_stop (and stops). DESARMAR is the kill switch (does not close what's open).
 */
export function ScalperBotControl({
  status,
  arm,
  disarm,
}: {
  status: BotStatus | null;
  arm: (profitTarget: number, lossStop: number) => Promise<void>;
  disarm: () => Promise<void>;
}) {
  const [target, setTarget] = useState("350");
  const [stop, setStop] = useState("900");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!status) return null;

  const profit = status.open_profit;
  const profitTone = profit > 0 ? "text-emerald-400" : profit < 0 ? "text-rose-400" : "text-zinc-400";

  async function onArm() {
    const t = Number(target);
    const s = Number(stop);
    if (!Number.isFinite(t) || t <= 0 || !Number.isFinite(s) || s <= 0) {
      setError("Meta e stop devem ser números positivos.");
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await arm(t, s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao armar o bot.");
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
        status.armed
          ? "border-fuchsia-600/70 bg-fuchsia-950/20"
          : "border-zinc-800 bg-zinc-950/40",
      )}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          {status.armed ? (
            <Zap className="size-4 animate-pulse text-fuchsia-400" />
          ) : (
            <Bot className="size-4 text-zinc-500" />
          )}
          <div className="text-sm font-semibold text-zinc-200">
            Bot scalper de explosão
            <span className="ml-2 text-[11px] font-normal text-zinc-500">
              abre · {status.open_count} posição(ões) · P&L{" "}
              <span className={cn("tabular-nums font-semibold", profitTone)}>
                {profit >= 0 ? "+" : "−"}
                {Math.abs(profit).toFixed(2)}
              </span>
              <span className="ml-2">
                sessão{" "}
                <span className="tabular-nums font-semibold text-zinc-400">
                  {status.realized >= 0 ? "+" : "−"}
                  {Math.abs(status.realized).toFixed(2)}
                </span>
              </span>
            </span>
          </div>
        </div>

        {!status.enabled ? (
          <span className="text-[11px] text-zinc-500">
            indisponível — precisa <code className="text-zinc-400">allow_auto_trade</code> + conta
            DEMO no collector
          </span>
        ) : status.armed ? (
          <div className="flex items-center gap-2">
            <span className="rounded bg-fuchsia-500/20 px-2 py-1 text-[11px] font-semibold uppercase tracking-wider text-fuchsia-300">
              OPERANDO · meta +${status.profit_target.toFixed(0)} / stop −${status.loss_stop.toFixed(0)}
            </span>
            <button
              onClick={onDisarm}
              disabled={busy}
              className="rounded bg-zinc-700 px-2.5 py-1 text-[11px] font-semibold text-zinc-100 hover:bg-zinc-600 disabled:opacity-50"
            >
              PARAR
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-[11px]">
            <label className="flex items-center gap-1 text-zinc-500">
              meta $
              <input
                type="number"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className="w-16 rounded border border-zinc-700 bg-zinc-900 px-1 py-1 tabular-nums text-zinc-100 outline-none"
              />
            </label>
            <label className="flex items-center gap-1 text-zinc-500">
              stop $
              <input
                type="number"
                value={stop}
                onChange={(e) => setStop(e.target.value)}
                className="w-16 rounded border border-zinc-700 bg-zinc-900 px-1 py-1 tabular-nums text-zinc-100 outline-none"
              />
            </label>
            <button
              onClick={onArm}
              disabled={busy}
              className="rounded bg-fuchsia-600 px-2.5 py-1 font-semibold text-white hover:bg-fuchsia-500 disabled:opacity-50"
            >
              OPERAR
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
