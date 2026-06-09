"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { TapeTrade } from "@/lib/types";
import { cn, fmtPrice } from "@/lib/utils";

/**
 * Profit-style time & sales tape:
 *  - newest trade flashes briefly (background pulse) so the eye latches on
 *  - aggressor color is bold; "big lots" (≥ p90 of the window) get a brighter row
 *  - sticky header summarises live aggression: Buy×Sell volume, delta, trades/s
 *  - rows scroll newest-first, capped at 80 so the DOM stays cheap to repaint
 */
export function TapePanel({ trades }: { trades: TapeTrade[] }) {
  // The last trade timestamp is the flash trigger. Re-render every 250ms while
  // a flash is active so the highlight fades out.
  const lastKey = trades.length > 0 ? `${trades[trades.length - 1].at}-${trades.length}` : "";
  const [flashUntil, setFlashUntil] = useState(0);
  const lastSeenRef = useRef("");
  useEffect(() => {
    if (lastKey && lastKey !== lastSeenRef.current) {
      lastSeenRef.current = lastKey;
      setFlashUntil(Date.now() + 350);
    }
  }, [lastKey]);
  const [now, setNow] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 120);
    return () => clearInterval(id);
  }, []);
  const flashActive = now < flashUntil;

  const recent = useMemo(() => [...trades].slice(-80).reverse(), [trades]);

  // 5-second aggression stats (rate + delta + counts) from the most recent
  // trades. Profit traders read this faster than the panel itself — the
  // "speedometer" of who's pressing right now.
  const stats = useMemo(() => computeStats(trades), [trades]);

  if (trades.length === 0) {
    return <p className="text-xs text-zinc-500">Sem trades na fita ainda…</p>;
  }

  // Big-lot threshold: top decile of recent volumes (min 1).
  const sorted = [...recent].map((t) => t.volume).sort((a, b) => a - b);
  const bigThreshold = sorted[Math.floor(sorted.length * 0.9)] ?? 1;

  return (
    <div className="text-xs tabular-nums">
      <TapeStats stats={stats} />

      <div className="mt-2 max-h-72 overflow-y-auto rounded border border-zinc-800">
        <div className="sticky top-0 z-10 flex justify-between bg-zinc-950/95 px-2 py-1 text-[10px] uppercase tracking-wider text-zinc-600 backdrop-blur">
          <span className="w-16">hora</span>
          <span className="flex-1 text-right">preço</span>
          <span className="w-12 text-right">vol</span>
        </div>
        {recent.map((t, i) => {
          const big = t.volume >= bigThreshold && t.volume > 1;
          const isNewest = i === 0;
          const buy = t.side === "buy";
          const sell = t.side === "sell";
          return (
            <div
              key={`${t.at}-${i}`}
              className={cn(
                "flex justify-between px-2 py-0.5 transition-colors",
                buy && "text-emerald-300",
                sell && "text-red-300",
                t.side === "unknown" && "text-zinc-400",
                big && "font-bold",
                big && buy && "bg-emerald-500/15",
                big && sell && "bg-red-500/15",
                isNewest && flashActive && buy && "bg-emerald-400/40",
                isNewest && flashActive && sell && "bg-red-400/40",
              )}
            >
              <span className="w-16 text-zinc-500">{fmtClock(t.at)}</span>
              <span className="flex-1 text-right">{fmtPrice(t.price)}</span>
              <span className="w-12 text-right">{fmtVol(t.volume)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TapeStats({ stats }: { stats: TapeStatsValue }) {
  const { buyVol, sellVol, delta, ratePerSec, count } = stats;
  const total = buyVol + sellVol;
  const buyPct = total > 0 ? (buyVol / total) * 100 : 50;
  const sellPct = 100 - buyPct;
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-[10px] uppercase tracking-wider">
        <span className="text-zinc-500">últimos 5s · {count} trades</span>
        <span className="text-zinc-500">
          <span className="text-zinc-200">{ratePerSec.toFixed(1)}</span> trades/s
        </span>
        <span className={cn(delta >= 0 ? "text-emerald-400" : "text-red-400")}>
          Δ {delta >= 0 ? "+" : ""}
          {fmtVol(delta)}
        </span>
      </div>
      <div className="flex h-1.5 overflow-hidden rounded-full bg-zinc-900">
        <div className="bg-emerald-500/80" style={{ width: `${buyPct}%` }} />
        <div className="bg-red-500/80" style={{ width: `${sellPct}%` }} />
      </div>
      <div className="flex justify-between text-[10px]">
        <span className="text-emerald-400">BUY {fmtVol(buyVol)}</span>
        <span className="text-red-400">SELL {fmtVol(sellVol)}</span>
      </div>
    </div>
  );
}

interface TapeStatsValue {
  buyVol: number;
  sellVol: number;
  delta: number;
  count: number;
  ratePerSec: number;
}

function computeStats(trades: TapeTrade[]): TapeStatsValue {
  const cutoff = Date.now() - 5_000;
  let buyVol = 0;
  let sellVol = 0;
  let count = 0;
  for (let i = trades.length - 1; i >= 0; i--) {
    const t = trades[i];
    const ts = new Date(t.at).getTime();
    if (ts < cutoff) break;
    count += 1;
    if (t.side === "buy") buyVol += t.volume;
    else if (t.side === "sell") sellVol += t.volume;
  }
  return {
    buyVol,
    sellVol,
    delta: buyVol - sellVol,
    count,
    ratePerSec: count / 5,
  };
}

function fmtVol(v: number): string {
  const a = Math.abs(v);
  if (a >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return v % 1 === 0 ? v.toFixed(0) : v.toFixed(2);
}

function fmtClock(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
