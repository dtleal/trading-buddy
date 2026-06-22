"use client";

import { fmtPrice } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { Position, TradeSignal } from "@/lib/types";

/**
 * Live open-position overlay for one symbol (read-only mirror of MT5). Shows
 * each position's side, entry → current, floating P&L and time-in-trade.
 *
 * Time-in-trade (`seconds_open`) is computed on the collector against the
 * broker's server clock — the frontend can't subtract a broker timestamp from a
 * browser clock without timezone skew, so we render the value as received. The
 * collector streams positions ~4×/s while open, so the timer advances smoothly;
 * if the feed pauses the timer pauses too, which the column's staleness dot
 * already signals.
 */
export function PositionPanel({
  positions,
  signals = [],
}: {
  positions: Position[];
  signals?: TradeSignal[];
}) {
  if (positions.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {positions.map((p) => (
        <PositionRow
          key={p.ticket}
          position={p}
          signals={signals.filter((s) => s.ticket === p.ticket)}
        />
      ))}
    </div>
  );
}

function PositionRow({ position: p, signals }: { position: Position; signals: TradeSignal[] }) {
  const secs = p.seconds_open;
  const long = p.side === "buy";
  const win = p.profit > 0;
  const flat = p.profit === 0;

  return (
    <div
      className={cn(
        "rounded-md border px-2 py-1.5",
        win
          ? "border-emerald-700/60 bg-emerald-950/30"
          : flat
            ? "border-zinc-700/60 bg-zinc-900/50"
            : "border-rose-700/60 bg-rose-950/30",
      )}
    >
      <div className="flex items-center justify-between text-[11px] font-semibold">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "rounded px-1 py-0.5 text-[10px] uppercase tracking-wider",
              long ? "bg-emerald-500/20 text-emerald-300" : "bg-rose-500/20 text-rose-300",
            )}
          >
            {long ? "LONG" : "SHORT"}
          </span>
          <span className="tabular-nums text-zinc-400">{p.volume} lt</span>
        </div>
        <span
          className={cn(
            "tabular-nums",
            win ? "text-emerald-400" : flat ? "text-zinc-400" : "text-rose-400",
          )}
        >
          {p.profit >= 0 ? "+" : "−"}
          {Math.abs(p.profit).toFixed(2)}
        </span>
      </div>

      <div className="mt-1 flex items-center justify-between text-[11px] tabular-nums text-zinc-300">
        <span>
          <span className="text-zinc-500">entr</span> {fmtPrice(p.price_open)}
          <span className="text-zinc-600"> → </span>
          {fmtPrice(p.price_current)}
        </span>
        <span className="text-zinc-400">{fmtDuration(secs)}</span>
      </div>

      {(p.sl != null || p.tp != null) && (
        <div className="mt-0.5 flex items-center gap-3 text-[10px] tabular-nums text-zinc-500">
          {p.sl != null && (
            <span>
              SL <span className="text-rose-400/80">{fmtPrice(p.sl)}</span>
            </span>
          )}
          {p.tp != null && (
            <span>
              TP <span className="text-emerald-400/80">{fmtPrice(p.tp)}</span>
            </span>
          )}
        </div>
      )}

      {signals.map((s) => (
        <SignalChip key={s.code} signal={s} />
      ))}
    </div>
  );
}

/** Inline alert under a position. Urgent (flow against) pulses red. */
function SignalChip({ signal }: { signal: TradeSignal }) {
  const urgent = signal.severity === "urgent";
  return (
    <div
      className={cn(
        "mt-1 flex items-center gap-1.5 rounded px-1.5 py-1 text-[11px] font-semibold",
        signal.stance === "against"
          ? cn("bg-rose-500/15 text-rose-300", urgent && "animate-pulse")
          : "bg-amber-500/15 text-amber-300",
      )}
    >
      <span aria-hidden>{signal.stance === "against" ? "⚠" : "✋"}</span>
      <span>{signal.message}</span>
    </div>
  );
}

/** Compact mm:ss / Ns duration for a scalp's time-in-trade. */
function fmtDuration(seconds: number): string {
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem.toString().padStart(2, "0")}s`;
}
