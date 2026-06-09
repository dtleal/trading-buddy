"use client";

import { useEffect, useRef } from "react";
import type { FootprintBar } from "@/lib/types";
import { cn, fmtPrice } from "@/lib/utils";

const VISIBLE_HEIGHT_PX = 260;
const DELTA_STRIP_HEIGHT_PX = 36;

/**
 * Footprint: executed volume per price within each time bar, split into
 * bid-aggressor (sell) vs ask-aggressor (buy) volume.
 *
 * Fixed-height container with internal scroll — the bar fills with prices over
 * its 1-minute window so a growing layout would push the rest of the page
 * around. We anchor the visible area on the POC so the trader's eye lands on
 * the highest-volume price by default.
 */
export function FootprintPanel({ bars }: { bars: FootprintBar[] }) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pocRef = useRef<HTMLDivElement | null>(null);

  // Re-center on POC whenever the POC price changes (not on every render —
  // otherwise manual scrolling fights the auto-anchor).
  const latest = bars.length > 0 ? bars[bars.length - 1] : null;
  const pocPrice = latest?.poc_price ?? null;
  const prevPocRef = useRef<number | null>(null);
  useEffect(() => {
    if (pocPrice == null || pocPrice === prevPocRef.current) return;
    prevPocRef.current = pocPrice;
    const el = pocRef.current;
    const container = scrollRef.current;
    if (el && container) {
      const top = el.offsetTop - container.clientHeight / 2 + el.clientHeight / 2;
      container.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
    }
  }, [pocPrice]);

  if (bars.length === 0 || !latest) {
    return (
      <div
        className="flex items-center justify-center text-xs text-zinc-500"
        style={{ height: VISIBLE_HEIGHT_PX + DELTA_STRIP_HEIGHT_PX + 20 }}
      >
        Sem footprint — aguardando trades.
      </div>
    );
  }

  const recent = bars.slice(-12);
  const maxCellVol = Math.max(
    1,
    ...latest.cells.map((c) => c.bid_volume + c.ask_volume),
  );

  return (
    <div className="space-y-2">
      <DeltaStrip bars={recent} />

      <div className="flex items-center justify-between text-[10px] uppercase tracking-wider text-zinc-500">
        <span>barra atual · {fmtClock(latest.bar_open)}</span>
        <span>
          Δ{" "}
          <span className={cn(latest.delta >= 0 ? "text-emerald-400" : "text-red-400")}>
            {latest.delta >= 0 ? "+" : ""}
            {fmtVol(latest.delta)}
          </span>
        </span>
      </div>

      <div
        ref={scrollRef}
        className="overflow-y-auto rounded border border-zinc-800 bg-zinc-950/40"
        style={{ height: VISIBLE_HEIGHT_PX }}
      >
        <div className="space-y-px p-1 text-xs tabular-nums">
          {latest.cells.map((c) => {
            const total = c.bid_volume + c.ask_volume;
            const dom = c.ask_volume >= c.bid_volume ? "ask" : "bid";
            const isPoc = pocPrice !== null && c.price === pocPrice;
            return (
              <div
                key={c.price}
                ref={isPoc ? pocRef : undefined}
                className={cn(
                  "flex items-center justify-between rounded-sm px-2 py-0.5",
                  isPoc && "ring-1 ring-amber-500/50",
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
                <span className="w-12 text-right text-emerald-300">
                  {fmtVol(c.ask_volume)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="flex justify-between text-[10px] uppercase tracking-wider text-zinc-600">
        <span>bid (vendedor)</span>
        <span>preço · POC</span>
        <span>ask (comprador)</span>
      </div>
    </div>
  );
}

function DeltaStrip({ bars }: { bars: FootprintBar[] }) {
  const maxAbs = Math.max(1, ...bars.map((b) => Math.abs(b.delta)));
  return (
    <div className="flex items-end gap-0.5" style={{ height: DELTA_STRIP_HEIGHT_PX }}>
      {bars.map((b) => {
        const h = Math.max(2, (Math.abs(b.delta) / maxAbs) * (DELTA_STRIP_HEIGHT_PX - 2));
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
