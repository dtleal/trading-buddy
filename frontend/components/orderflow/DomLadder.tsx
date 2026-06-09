"use client";

import type { OrderBookSnapshot } from "@/lib/types";
import { cn, fmtPrice } from "@/lib/utils";

/**
 * Depth-of-market ladder: resting limit liquidity per price.
 * Asks (red) stacked on top with the best ask at the bottom, the spread in the
 * middle, bids (green) below with the best bid at the top. Size bars are scaled
 * to the largest resting size on screen so big resting orders pop visually.
 */
export function DomLadder({ book }: { book: OrderBookSnapshot | null | undefined }) {
  if (!book || (book.bids.length === 0 && book.asks.length === 0)) {
    return (
      <p className="text-xs text-zinc-500">
        Sem profundidade (DOM) — seu broker pode não publicar book para este ativo.
      </p>
    );
  }

  const maxVol = Math.max(
    1,
    ...book.bids.map((l) => l.volume),
    ...book.asks.map((l) => l.volume),
  );
  // Asks: show worst→best top-to-bottom so the best ask sits next to the spread.
  const asks = [...book.asks].slice(0, 12).reverse();
  const bids = [...book.bids].slice(0, 12);

  const bestBid = book.bids[0]?.price;
  const bestAsk = book.asks[0]?.price;
  const spread = bestBid != null && bestAsk != null ? bestAsk - bestBid : null;

  return (
    <div className="space-y-0.5 text-xs tabular-nums">
      {asks.map((lv) => (
        <LadderRow key={`a-${lv.price}`} side="ask" price={lv.price} volume={lv.volume} maxVol={maxVol} />
      ))}
      <div className="flex items-center justify-center gap-2 py-1 text-[11px] text-zinc-500">
        <span>spread</span>
        <span className="text-zinc-300">{spread != null ? fmtPrice(spread) : "—"}</span>
      </div>
      {bids.map((lv) => (
        <LadderRow key={`b-${lv.price}`} side="bid" price={lv.price} volume={lv.volume} maxVol={maxVol} />
      ))}
    </div>
  );
}

function LadderRow({
  side,
  price,
  volume,
  maxVol,
}: {
  side: "bid" | "ask";
  price: number;
  volume: number;
  maxVol: number;
}) {
  const pct = Math.max(2, (volume / maxVol) * 100);
  const isBid = side === "bid";
  return (
    <div className="relative flex h-5 items-center justify-between overflow-hidden rounded-sm px-2">
      <div
        className={cn(
          "absolute inset-y-0",
          isBid ? "right-0 bg-emerald-500/15" : "right-0 bg-red-500/15",
        )}
        style={{ width: `${pct}%` }}
      />
      <span className={cn("relative z-10", isBid ? "text-emerald-300" : "text-red-300")}>
        {fmtPrice(price)}
      </span>
      <span className="relative z-10 text-zinc-300">{fmtVol(volume)}</span>
    </div>
  );
}

function fmtVol(v: number): string {
  if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return v % 1 === 0 ? v.toFixed(0) : v.toFixed(2);
}
