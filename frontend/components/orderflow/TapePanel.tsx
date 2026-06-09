"use client";

import type { TapeTrade } from "@/lib/types";
import { cn, fmtPrice } from "@/lib/utils";

/**
 * Time & sales tape: most recent executed trades, newest first. Color by
 * aggressor — green = buy (lifted ask), red = sell (hit bid), zinc = unknown.
 * Big prints are emphasised so size sweeps stand out.
 */
export function TapePanel({ trades }: { trades: TapeTrade[] }) {
  if (trades.length === 0) {
    return <p className="text-xs text-zinc-500">Sem trades na fita ainda…</p>;
  }
  const recent = [...trades].slice(-40).reverse();
  const maxVol = Math.max(1, ...recent.map((t) => t.volume));

  return (
    <div className="max-h-72 space-y-px overflow-y-auto text-xs tabular-nums">
      <div className="sticky top-0 flex justify-between bg-zinc-950/80 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-600 backdrop-blur">
        <span>hora</span>
        <span>preço</span>
        <span>vol</span>
      </div>
      {recent.map((t, i) => {
        const big = t.volume >= maxVol * 0.6;
        return (
          <div
            key={`${t.at}-${i}`}
            className={cn(
              "flex justify-between px-2 py-0.5",
              t.side === "buy" && "text-emerald-300",
              t.side === "sell" && "text-red-300",
              t.side === "unknown" && "text-zinc-400",
              big && "font-semibold",
            )}
          >
            <span className="text-zinc-500">{fmtClock(t.at)}</span>
            <span>{fmtPrice(t.price)}</span>
            <span className={cn(big && (t.side === "buy" ? "text-emerald-200" : "text-red-200"))}>
              {fmtVol(t.volume)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function fmtVol(v: number): string {
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return v % 1 === 0 ? v.toFixed(0) : v.toFixed(2);
}

function fmtClock(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
