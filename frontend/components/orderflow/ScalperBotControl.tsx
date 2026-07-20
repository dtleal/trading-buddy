"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Zap, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BotStatus } from "@/lib/types";

// The three symbols the bot trades, in display order (SPX shows as USA500).
const LOT_ASSETS: { key: string; label: string }[] = [
  { key: "USTEC", label: "USTEC" },
  { key: "SPX", label: "USA500" },
  { key: "GOLD", label: "GOLD" },
];

/**
 * Explosion-scalper bot control. This is the only thing that OPENS positions
 * (demo only), so it's visually loud and the controls are inert unless the
 * collector permits auto-trade on a demo account.
 *
 * Lot sizes per symbol are configurable here (panel "Lotes") — dial them down to
 * the 0.01 minimum to test the bot with the smallest possible risk. Entries open
 * on detected bursts, up to 6 per symbol. Exit: closes the whole account at
 * +profit_target, or at −loss_stop (and stops). DESARMAR is the kill switch.
 */
export function ScalperBotControl({
  status,
  arm,
  saveLots,
  disarm,
}: {
  status: BotStatus | null;
  arm: (profitTarget: number, lossStop: number, lots?: Record<string, number>) => Promise<void>;
  saveLots: (lots: Record<string, number>) => Promise<void>;
  disarm: () => Promise<void>;
}) {
  const [target, setTarget] = useState("350");
  const [stop, setStop] = useState("900");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showLots, setShowLots] = useState(false);

  // Editable lot fields (strings while typing). Synced from the server until the
  // user edits them, so the inputs always start from what's actually active.
  const [lots, setLots] = useState<Record<string, string>>({});
  const dirty = useRef(false);
  useEffect(() => {
    if (dirty.current || !status) return;
    const next: Record<string, string> = {};
    for (const a of LOT_ASSETS) next[a.key] = String(status.lots[a.key] ?? "");
    setLots(next);
  }, [status]);

  if (!status) return null;

  const profit = status.open_profit;
  const profitTone = profit > 0 ? "text-emerald-400" : profit < 0 ? "text-rose-400" : "text-zinc-400";

  /** Parse + validate the lot inputs into a {SYMBOL: number} map. */
  function parseLots(): Record<string, number> | null {
    const out: Record<string, number> = {};
    for (const a of LOT_ASSETS) {
      const raw = lots[a.key];
      if (raw == null || raw === "") continue; // leave unchanged on the server
      const n = Number(raw);
      if (!Number.isFinite(n) || n <= 0) {
        setError(`Lote de ${a.label} deve ser um número > 0.`);
        return null;
      }
      out[a.key] = n;
    }
    return out;
  }

  function setAllLots(value: string) {
    dirty.current = true;
    setLots(Object.fromEntries(LOT_ASSETS.map((a) => [a.key, value])));
  }

  async function onArm() {
    const t = Number(target);
    const s = Number(stop);
    if (!Number.isFinite(t) || t <= 0 || !Number.isFinite(s) || s <= 0) {
      setError("Meta e stop devem ser números positivos.");
      return;
    }
    const parsedLots = parseLots();
    if (parsedLots === null) return;
    setError(null);
    setBusy(true);
    try {
      await arm(t, s, parsedLots);
      dirty.current = false;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao armar o bot.");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveLots() {
    const parsedLots = parseLots();
    if (parsedLots === null) return;
    setError(null);
    setBusy(true);
    try {
      await saveLots(parsedLots);
      dirty.current = false;
      setShowLots(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao salvar lotes.");
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

  // Human-readable summary of the active lot sizes (from the server).
  const lotsSummary = LOT_ASSETS.map(
    (a) => `${a.label} ${status.lots[a.key] ?? "—"}`,
  ).join(" · ");

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
              LIGADO · meta +${status.profit_target.toFixed(0)} / stop −${status.loss_stop.toFixed(0)}
            </span>
            <button
              onClick={onDisarm}
              disabled={busy}
              className="rounded bg-zinc-700 px-2.5 py-1 text-[11px] font-semibold text-zinc-100 hover:bg-zinc-600 disabled:opacity-50"
            >
              DESLIGAR
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-[11px]">
            <button
              onClick={() => setShowLots((v) => !v)}
              className={cn(
                "flex items-center gap-1 rounded border px-2 py-1 font-semibold",
                showLots
                  ? "border-fuchsia-600/70 bg-fuchsia-950/30 text-fuchsia-200"
                  : "border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800",
              )}
            >
              <SlidersHorizontal className="size-3" />
              Lotes
            </button>
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
              LIGAR
            </button>
          </div>
        )}
      </div>

      {/* Active lot sizes — always visible so it's clear what the bot will trade. */}
      <div className="mt-1.5 text-[10px] text-zinc-500">
        lotes por ativo: <span className="tabular-nums text-zinc-400">{lotsSummary}</span>
      </div>

      {/* Lot-config panel (only when disarmed). */}
      {!status.armed && showLots && (
        <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-900/50 p-2.5">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-300">
              Configurar lotes por ativo
            </span>
            <button
              onClick={() => setAllLots("0.01")}
              className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-[10px] font-semibold text-zinc-200 hover:bg-zinc-700"
            >
              mín 0.01 em tudo
            </button>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            {LOT_ASSETS.map((a) => (
              <label key={a.key} className="flex flex-col gap-1 text-[10px] text-zinc-500">
                <span className="uppercase tracking-wider">{a.label}</span>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={lots[a.key] ?? ""}
                  onChange={(e) => {
                    dirty.current = true;
                    setLots((prev) => ({ ...prev, [a.key]: e.target.value }));
                  }}
                  className="w-20 rounded border border-zinc-700 bg-zinc-900 px-1.5 py-1 tabular-nums text-zinc-100 outline-none"
                />
              </label>
            ))}
            <button
              onClick={onSaveLots}
              disabled={busy}
              className="rounded bg-fuchsia-600 px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-fuchsia-500 disabled:opacity-50"
            >
              Salvar lotes
            </button>
          </div>
          <p className="mt-2 text-[10px] text-zinc-500">
            Cada entrada envia 1 ordem a mercado + grade de limites no mesmo lote. 0.01 é o mínimo
            do broker — ideal pra testar o bot.
          </p>
        </div>
      )}

      {(error || status.last_result) && (
        <div className={cn("mt-1.5 text-[10px]", error ? "text-rose-400" : "text-zinc-500")}>
          {error ?? status.last_result}
        </div>
      )}
    </div>
  );
}
