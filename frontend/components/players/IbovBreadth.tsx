"use client";

import type { IbovResponse } from "@/lib/types";

/**
 * How many names are moving, and by how much — the other half of the top-10
 * panel. The rows are cumulative (the 1% row includes everything past 2%), so
 * they read top-down as "how far does the move go": a day with 60 names up but
 * nothing past 1% is a drift, the same 60 with twenty past 2% is a trend.
 */
export function IbovBreadth({ data }: { data: IbovResponse }) {
  const rows = [...data.niveis].reverse();

  return (
    <section className="rounded border border-zinc-800 bg-zinc-950/60 p-3">
      <header className="mb-2 flex items-baseline justify-between text-[11px]">
        <span className="font-semibold uppercase tracking-wide text-zinc-400">
          Ações por nível
        </span>
        <span className="text-zinc-300">
          {data.abertas}/{data.universo} com cotação
        </span>
      </header>

      <div className="space-y-[2px]">
        {rows.map((row) => (
          <div
            key={row.nivel}
            className="flex items-center gap-2 rounded-sm bg-zinc-900/40 px-2 py-[3px] text-[11px] tabular-nums"
          >
            <span className="w-10 text-zinc-400">
              {row.nivel.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%
            </span>
            <span className="flex-1 text-right text-sky-400">{row.sobe || ""}</span>
            <span className="flex-1 text-right text-red-400">{row.cai || ""}</span>
          </div>
        ))}
      </div>

      {data.pct_sobe !== null && (
        <div className="mt-2 flex h-5 overflow-hidden rounded-sm text-[11px] font-semibold">
          <div
            className="flex items-center justify-center bg-sky-900 text-sky-100"
            style={{ width: `${data.pct_sobe}%` }}
          >
            {data.pct_sobe >= 12 && `${Math.round(data.pct_sobe)}%`}
          </div>
          <div className="flex flex-1 items-center justify-center bg-red-900 text-red-100">
            {100 - data.pct_sobe >= 12 && `${Math.round(100 - data.pct_sobe)}%`}
          </div>
        </div>
      )}
    </section>
  );
}
