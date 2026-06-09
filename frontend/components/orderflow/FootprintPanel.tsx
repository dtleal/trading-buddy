"use client";

import type { FootprintBar } from "@/lib/types";
import { cn, fmtPrice } from "@/lib/utils";

/**
 * Footprint: executed volume per price within each time bar, split into
 * bid-aggressor (sell) vs ask-aggressor (buy) volume. The latest (in-progress)
 * bar is shown as a price ladder of bid×ask; a delta strip summarises the
 * recent bars so the trader sees the aggression trend at a glance.
 */
export function FootprintPanel({ bars }: { bars: FootprintBar[] }) {
  if (bars.length === 0) {
    return (
      <p className="text-xs text-zinc-500">
        Sem footprint — depende do broker enviar trades (volume executado).
      </p>
    );
  }
  const latest = bars[bars.length - 1];
  const recent = bars.slice(-12);
  const maxCellVol = Math.max(
    1,
    ...latest.cells.map((c) => c.bid_volume + c.ask_volume),
  );

  return (
    <div className="space-y-3">
      <DeltaStrip bars={recent} />
      <div>
        <div className="mb-1 flex items-center justify-between text-[11px] text-zinc-500">
          <span>barra atual · {fmtClock(latest.bar_open)}</span>
          <span>
            Δ{" "}
            <span className={cn(latest.delta >= 0 ? "text-emerald-400" : "text-red-400")}>
              {latest.delta >= 0 ? "+" : ""}
              {fmtVol(latest.delta)}
            </span>
          </span>
        </div>
        <div className="space-y-0.5 text-xs tabular-nums">
          {latest.cells.map((c) => {
            const total = c.bid_volume + c.ask_volume;
            const dom = c.ask_volume >= c.bid_volume ? "ask" : "bid";
            const isPoc = latest.poc_price !== null && c.price === latest.poc_price;
            return (
              <div
                key={c.price}
                className={cn(
                  "flex items-center justify-between rounded-sm px-2 py-0.5",
                  isPoc && "ring-1 ring-amber-500/40",
                )}
                style={{
                  background:
                    dom === "ask"
                      ? `rgba(16,185,129,${0.08 + 0.25 * (total / maxCellVol)})`
                      : `rgba(239,68,68,${0.08 + 0.25 * (total / maxCellVol)})`,
                }}
              >
                <span className="w-12 text-red-300">{fmtVol(c.bid_volume)}</span>
                <span className="text-zinc-300">{fmtPrice(c.price)}</span>
                <span className="w-12 text-right text-emerald-300">{fmtVol(c.ask_volume)}</span>
              </div>
            );
          })}
        </div>
        <div className="mt-1 flex justify-between text-[10px] uppercase tracking-wider text-zinc-600">
          <span>bid (vendedor)</span>
          <span>preço · POC</span>
          <span>ask (comprador)</span>
        </div>
      </div>
    </div>
  );
}

function DeltaStrip({ bars }: { bars: FootprintBar[] }) {
  const maxAbs = Math.max(1, ...bars.map((b) => Math.abs(b.delta)));
  return (
    <div className="flex items-end gap-0.5" style={{ height: 36 }}>
      {bars.map((b) => {
        const h = Math.max(2, (Math.abs(b.delta) / maxAbs) * 34);
        return (
          <div
            key={b.bar_open}
            title={`${fmtClock(b.bar_open)} · Δ ${b.delta >= 0 ? "+" : ""}${fmtVol(b.delta)}`}
            className={cn("flex-1 rounded-sm", b.delta >= 0 ? "bg-emerald-500/60" : "bg-red-500/60")}
            style={{ height: h }}
          />
        );
      })}
    </div>
  );
}

function fmtVol(v: number): string {
  const a = Math.abs(v);
  if (a >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return v % 1 === 0 ? v.toFixed(0) : v.toFixed(1);
}

function fmtClock(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
