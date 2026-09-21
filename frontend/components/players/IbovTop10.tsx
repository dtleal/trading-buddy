"use client";

import { cn } from "@/lib/utils";
import type { IbovResponse } from "@/lib/types";

/**
 * The ten heaviest names in the Ibovespa, side by side.
 *
 * The WIN is the index, so "why is it going up" is almost always one of these
 * ten. The bar is sized by **contribution** (weight × move), not by the move
 * itself: a 3% jump on a 0,5% weight moves nothing, and drawing it as tall as
 * Vale would be a lie the eye falls for.
 */
export function IbovTop10({ data }: { data: IbovResponse }) {
  const peak = Math.max(...data.acoes.map((a) => Math.abs(a.contrib_pct ?? 0)), 0.01);

  return (
    <section className="rounded border border-zinc-800 bg-zinc-950/60 p-3">
      <header className="mb-2 flex flex-wrap items-baseline gap-x-3 text-[11px]">
        <span className="font-semibold uppercase tracking-wide text-zinc-400">
          Top 10 pesos do Ibov
        </span>
        <span className="text-zinc-300">{data.peso.toFixed(1)}% do índice</span>
        {data.contrib_pct !== null && (
          <span className="text-zinc-300">
            empurrando{" "}
            <span className={data.contrib_pct >= 0 ? "text-emerald-400" : "text-red-400"}>
              {signed(data.contrib_pct)}
            </span>{" "}
            hoje
          </span>
        )}
        <span className="ml-auto text-zinc-400">
          carteira {data.carteira} · cotação atrasada 15 min
        </span>
      </header>

      <div className="flex gap-1">
        {data.acoes.map((acao) => {
          const up = (acao.contrib_pct ?? 0) >= 0;
          const width = Math.max(6, (Math.abs(acao.contrib_pct ?? 0) / peak) * 100);
          return (
            <div key={acao.cod} className="flex min-w-0 flex-1 flex-col gap-1">
              <div
                className={cn(
                  "text-center text-[11px] tabular-nums",
                  acao.var_pct === null ? "text-zinc-400" : up ? "text-emerald-400" : "text-red-400",
                )}
              >
                {acao.var_pct === null ? "—" : signed(acao.var_pct)}
              </div>
              <div className="h-1.5 w-full rounded-sm bg-zinc-900">
                <div
                  className={cn("h-full rounded-sm", up ? "bg-sky-700" : "bg-red-800")}
                  style={{ width: `${width}%`, marginLeft: up ? 0 : "auto" }}
                />
              </div>
              <div className="truncate text-center text-[11px] text-zinc-300">
                {acao.cod} <span className="text-zinc-400">{acao.peso.toFixed(1)}%</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function signed(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}
