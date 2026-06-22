"use client";

import { useEffect, useRef, useState } from "react";
import { fmtPrice } from "@/lib/utils";
import type { OrderFlowSnapshot } from "@/lib/types";

// Rolling tick window. Like an MT5 tick chart, the X axis is by quote change,
// not uniform time — one point per actual bid/ask move.
const MAX_POINTS = 140;
const VIEW_W = 300;
const VIEW_H = 120;

// If the quote stops changing for this long while the feed is otherwise live,
// the source is frozen (e.g. a broker's mirrored DOM that stops updating — the
// exact failure that once left this chart silently stuck at "Coletando…").
// Surface it loudly instead of pretending we're still warming up.
const QUOTE_STALE_MS = 12_000;

type Pt = { bid: number; ask: number };

/**
 * Real-time bid/ask tick chart with the spread shaded between the two lines —
 * the MT5 tick-chart look. Best bid/ask (top of book) is the one genuinely real
 * signal on these feeds, so this replaces the (mirrored, demo-grade) DOM ladder.
 *
 * Points are accumulated from each incoming snapshot's top of book; a new point
 * is added only when the quote actually changes.
 */
export function BidAskChart({ flow, now }: { flow: OrderFlowSnapshot | undefined; now: number }) {
  const [points, setPoints] = useState<Pt[]>([]);
  const lastQuote = useRef<string>("");
  // Wall-clock of the last actual quote change. Drives the staleness guard —
  // we can't compare book.asof to the snapshot's asof because they come from
  // different clocks (broker server time vs collector wall-clock), so freshness
  // is tracked client-side from when a new point actually lands.
  const lastChangeAt = useRef<number>(0);

  const bid = flow?.book?.bids?.[0]?.price ?? null;
  const ask = flow?.book?.asks?.[0]?.price ?? null;

  useEffect(() => {
    if (bid == null || ask == null) return;
    const key = `${bid}:${ask}`;
    if (key === lastQuote.current) return; // unchanged quote → no new tick
    lastQuote.current = key;
    lastChangeAt.current = Date.now();
    setPoints((prev) => {
      const next = prev.length >= MAX_POINTS ? prev.slice(prev.length - MAX_POINTS + 1) : prev.slice();
      next.push({ bid, ask });
      return next;
    });
  }, [bid, ask]);

  // Quote hasn't moved in a while though we've seen at least one — frozen source.
  const stale =
    lastChangeAt.current > 0 && now > 0 && now - lastChangeAt.current > QUOTE_STALE_MS;

  if (points.length < 2 || bid == null || ask == null) {
    return (
      <div className="flex h-[120px] items-center justify-center text-center text-xs text-zinc-500">
        {stale ? (
          <span className="text-amber-500">Bid/Ask sem atualização (cotação parada)</span>
        ) : (
          "Coletando cotações…"
        )}
      </div>
    );
  }

  // Y domain across the visible window, padded so the lines aren't glued to the
  // edges. Guard the flat case (lo == hi) to avoid divide-by-zero.
  let lo = Infinity;
  let hi = -Infinity;
  for (const p of points) {
    if (p.bid < lo) lo = p.bid;
    if (p.ask > hi) hi = p.ask;
  }
  const span = hi - lo || Math.max(hi * 1e-4, 1e-6);
  const pad = span * 0.18;
  const yLo = lo - pad;
  const yHi = hi + pad;

  const xAt = (i: number) => (i / (points.length - 1)) * VIEW_W;
  const yAt = (price: number) => VIEW_H - ((price - yLo) / (yHi - yLo)) * VIEW_H;

  const askPts = points.map((p, i) => `${xAt(i).toFixed(2)},${yAt(p.ask).toFixed(2)}`);
  const bidPts = points.map((p, i) => `${xAt(i).toFixed(2)},${yAt(p.bid).toFixed(2)}`);
  // Spread band: ask line left→right, then bid line right→left.
  const band = `${askPts.join(" ")} ${bidPts.slice().reverse().join(" ")}`;

  const spread = ask - bid;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="none"
        className="h-[120px] w-full"
      >
        <polygon points={band} fill="rgb(139 92 246 / 0.12)" stroke="none" />
        <polyline
          points={bidPts.join(" ")}
          fill="none"
          stroke="rgb(16 185 129)"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
        <polyline
          points={askPts.join(" ")}
          fill="none"
          stroke="rgb(244 63 94)"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      {/* live read-out */}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between px-1 text-[11px] font-semibold tabular-nums">
        <span className="text-rose-400">ask {fmtPrice(ask)}</span>
        <span className="text-zinc-500">spread {fmtPrice(spread)}</span>
        <span className="text-emerald-400">bid {fmtPrice(bid)}</span>
      </div>

      {stale && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center pb-0.5 text-[10px] font-semibold text-amber-500">
          cotação parada
        </div>
      )}
    </div>
  );
}
