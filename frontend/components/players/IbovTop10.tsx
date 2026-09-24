"use client";

import { cn } from "@/lib/utils";
import type { IbovResponse } from "@/lib/types";

/**
 * The ten heaviest names in the Ibovespa, one per row (it sits in the side column).
 *
 * The WIN is the index, so "why is it going up" is almost always one of these
 * ten. The bar is sized by **contribution** (weight × move), not by the move
 * itself: a 3% jump on a 0,5% weight moves nothing, and drawing it as tall as
 * Vale would be a lie the eye falls for.
 */
export function IbovTop10({ data }: { data: IbovResponse }) {
  // Maior alta no topo, maior queda embaixo; sem cotação vai pro fim.
  const acoes = [...data.acoes].sort(
    (a, b) => (b.var_pct ?? -Infinity) - (a.var_pct ?? -Infinity),
  );
  // Share of the top-10 weight that is up today, same bar as "Ações por nível".
  const pesoSobe = acoes.reduce((sum, a) => sum + ((a.var_pct ?? 0) > 0 ? a.peso : 0), 0);
  const pesoCai = acoes.reduce((sum, a) => sum + ((a.var_pct ?? 0) < 0 ? a.peso : 0), 0);
  const pctSobe = pesoSobe + pesoCai > 0 ? (100 * pesoSobe) / (pesoSobe + pesoCai) : null;
  const peak = Math.max(...data.acoes.map((a) => Math.abs(a.contrib_pct ?? 0)), 0.01);

  return (
    <section className="rounded border border-zinc-800 bg-zinc-950/60 p-3">
      <header className="mb-2 text-[11px]">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-semibold uppercase tracking-wide text-zinc-400">
            Top 10 do Ibov
          </span>
          <span className="text-zinc-300">{data.peso.toFixed(1)}% do índice</span>
        </div>
        {data.contrib_pct !== null && (
          <div className="text-zinc-300">
            empurrando{" "}
            <span className={data.contrib_pct >= 0 ? "text-emerald-400" : "text-red-400"}>
              {signed(data.contrib_pct)}
            </span>{" "}
            hoje
          </div>
        )}
        <div className="text-zinc-400">carteira {data.carteira} · atraso 15 min</div>
      </header>

      <div className="space-y-1">
        {acoes.map((acao) => {
          const up = (acao.contrib_pct ?? 0) >= 0;
          const width = Math.max(6, (Math.abs(acao.contrib_pct ?? 0) / peak) * 100);
          return (
            <div key={acao.cod} className="flex items-center gap-2 text-[11px] tabular-nums">
              <span className="w-12 text-zinc-300">{acao.cod}</span>
              <span className="w-8 text-right text-zinc-400">{acao.peso.toFixed(1)}%</span>
              <div className="h-1.5 flex-1 rounded-sm bg-zinc-900">
                <div
                  className={cn("h-full rounded-sm", up ? "bg-sky-700" : "bg-red-800")}
                  style={{ width: `${width}%`, marginLeft: up ? 0 : "auto" }}
                />
              </div>
              <span
                className={cn(
                  "w-12 text-right",
                  acao.var_pct === null ? "text-zinc-400" : up ? "text-emerald-400" : "text-red-400",
                )}
              >
                {acao.var_pct === null ? "—" : signed(acao.var_pct)}
              </span>
            </div>
          );
        })}
      </div>

      {pctSobe !== null && (
        <div
          className="mt-2 flex h-5 overflow-hidden rounded-sm text-[11px] font-semibold"
          title="peso subindo × peso caindo"
        >
          <div
            className="flex items-center justify-center bg-sky-900 text-sky-100"
            style={{ width: `${pctSobe}%` }}
          >
            {pctSobe >= 12 && `${Math.round(pctSobe)}%`}
          </div>
          <div className="flex flex-1 items-center justify-center bg-red-900 text-red-100">
            {100 - pctSobe >= 12 && `${Math.round(100 - pctSobe)}%`}
          </div>
        </div>
      )}
    </section>
  );
}

function signed(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}
