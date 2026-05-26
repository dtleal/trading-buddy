"use client";

import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import type { DashboardTick, PriceQuote } from "@/lib/types";
import { cn, fmtPct, fmtPrice } from "@/lib/utils";

export function PricesPanel({ tick }: { tick: DashboardTick | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ativos</CardTitle>
        <CardDescription>
          USTEC · SPX · GOLD — preço atual, variação do dia e distância da MM 200 (daily)
        </CardDescription>
      </CardHeader>
      <CardContent>
        {tick ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {Object.entries(tick.market.assets).map(([sym, quote]) => (
              <AssetCard key={sym} symbol={sym} quote={quote} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-zinc-500">Aguardando primeiro tick…</p>
        )}
      </CardContent>
    </Card>
  );
}

function AssetCard({ symbol, quote }: { symbol: string; quote: PriceQuote }) {
  const distPct =
    quote.ma200_d !== null
      ? ((quote.price - quote.ma200_d) / quote.ma200_d) * 100
      : null;
  const change = quote.change_pct ?? 0;
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex items-center justify-between text-xs uppercase tracking-wider text-zinc-500">
        <span>{symbol}</span>
        <Trend value={change} />
      </div>
      <div className="mt-2 text-3xl font-semibold tabular-nums text-zinc-100">
        {fmtPrice(quote.price)}
      </div>
      <div
        className={cn(
          "mt-0.5 text-sm tabular-nums",
          change >= 0 ? "text-emerald-400" : "text-red-400",
        )}
      >
        {fmtPct(quote.change_pct)} hoje
      </div>
      <div className="mt-3 border-t border-zinc-800 pt-2 text-xs text-zinc-400">
        <div className="flex justify-between">
          <span>MM 200d</span>
          <span className="tabular-nums">{fmtPrice(quote.ma200_d)}</span>
        </div>
        {distPct !== null && (
          <div className="mt-0.5 flex justify-between">
            <span>distância</span>
            <span
              className={cn(
                "tabular-nums",
                distPct >= 0 ? "text-emerald-400" : "text-red-400",
              )}
            >
              {fmtPct(distPct)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function Trend({ value }: { value: number }) {
  if (value > 0) return <ArrowUp className="size-4 text-emerald-400" />;
  if (value < 0) return <ArrowDown className="size-4 text-red-400" />;
  return <Minus className="size-4 text-zinc-500" />;
}
