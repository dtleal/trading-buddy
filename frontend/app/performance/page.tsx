"use client";

import { useState } from "react";
import { Header } from "@/components/shared/Header";
import { BreakdownTable } from "@/components/performance/BreakdownTable";
import { EquityCurveChart } from "@/components/performance/EquityCurveChart";
import { PerformanceFilterBar } from "@/components/performance/PerformanceFilterBar";
import { PerformanceKpis } from "@/components/performance/PerformanceKpis";
import { PeriodTable } from "@/components/performance/PeriodTable";
import { SummaryPanel } from "@/components/performance/SummaryPanel";
import { TradesTable } from "@/components/performance/TradesTable";
import { usePerformance } from "@/hooks/usePerformance";
import type { PerformanceQuery } from "@/lib/types";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "resumo", label: "Resumo" },
  { key: "operacoes", label: "Operações" },
] as const;

type Tab = (typeof TABS)[number]["key"];

/**
 * Performance tab: every closed trade of the account — hand-placed and the
 * scalper bot's — read straight from the broker's deal history. Laid out like
 * the Profit (Nelogica) performance report: a **Resumo** tab with the stat
 * list, the capital curve and the period/asset breakdowns, and an
 * **Operações** tab with the trade list.
 */
export default function PerformancePage() {
  const [query, setQuery] = useState<PerformanceQuery>({ preset: "month", source: "all" });
  const [tab, setTab] = useState<Tab>("resumo");
  const { report, loading, error } = usePerformance(query);

  return (
    <>
      <Header />
      <main className="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-4 px-4 py-6">
        <PerformanceFilterBar
          query={query}
          onChange={setQuery}
          availableSymbols={report?.available_symbols ?? []}
        />

        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                tab === t.key
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200",
              )}
            >
              {t.label}
              {t.key === "operacoes" && report ? ` (${report.summary.trades})` : ""}
            </button>
          ))}
        </div>

        {error && (
          <div className="rounded-lg border border-red-900 bg-red-950/40 px-4 py-3 text-xs text-red-300">
            falha ao carregar a performance: {error}
          </div>
        )}

        {loading && !report && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-4 py-8 text-center text-xs text-zinc-500">
            carregando operações…
          </div>
        )}

        {report && report.summary.trades === 0 && report.available_symbols.length === 0 && (
          <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-4 py-3 text-xs text-zinc-500">
            Sem histórico ainda. O collector no Windows envia as operações
            fechadas a cada ~5 minutos — deixe o MT5 aberto e logado.
          </div>
        )}

        {report && tab === "resumo" && (
          <>
            <PerformanceKpis report={report} />
            <EquityCurveChart report={report} />
            <SummaryPanel report={report} />

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <PeriodTable report={report} />
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <BreakdownTable
                  title="Por ativo"
                  description="onde o dinheiro é feito (ou perdido)"
                  rows={report.by_symbol}
                />
                <BreakdownTable
                  title="Manual × bot"
                  description="quem operou melhor"
                  rows={report.by_source}
                />
                <BreakdownTable
                  title="Compra × venda"
                  description="lado da operação"
                  rows={report.by_side}
                />
                <BreakdownTable
                  title="Por dia da semana"
                  description="fechamento em UTC"
                  rows={report.by_weekday}
                />
              </div>
            </div>

            <BreakdownTable
              title="Por hora do dia (UTC)"
              description="a hora em que a operação foi fechada"
              rows={report.by_hour}
            />
          </>
        )}

        {report && tab === "operacoes" && <TradesTable report={report} />}

        {report && (
          <p className="text-[11px] text-zinc-600">
            Fonte: histórico de negócios (deals) da própria corretora, lido pelo
            collector — o mesmo dinheiro que entrou na conta, já com comissão e
            swap. Depósitos e saques entram como degrau na curva e{" "}
            <span className="text-zinc-400">nunca como resultado</span>: o
            retorno % é medido sobre o capital (saldo no início + depósitos do
            período). Datas e horas dos agrupamentos estão em UTC. MEP/MEN e
            máximo de contratos do relatório do Profit não têm equivalente aqui —
            o histórico da corretora não guarda o caminho do preço dentro da
            operação.
            {report.asof &&
              ` Última leitura: ${new Date(report.asof).toLocaleString("pt-BR")}.`}
          </p>
        )}
      </main>
    </>
  );
}
