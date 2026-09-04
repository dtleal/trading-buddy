"use client";

import { useState } from "react";
import { Header } from "@/components/shared/Header";
import { BreakdownTable } from "@/components/performance/BreakdownTable";
import { EquityCurveChart } from "@/components/performance/EquityCurveChart";
import { PerformanceFilterBar } from "@/components/performance/PerformanceFilterBar";
import { PerformanceKpis } from "@/components/performance/PerformanceKpis";
import { PeriodTable } from "@/components/performance/PeriodTable";
import { TradesTable } from "@/components/performance/TradesTable";
import { usePerformance } from "@/hooks/usePerformance";
import type { PerformanceQuery } from "@/lib/types";

/**
 * Performance tab: every closed trade of the account — hand-placed and the
 * scalper bot's — read straight from the broker's deal history, with the
 * numbers that say whether the trading is working: hit rate, win/loss split,
 * profit factor, risk-return, drawdown and the equity curve.
 */
export default function PerformancePage() {
  const [query, setQuery] = useState<PerformanceQuery>({ preset: "month", source: "all" });
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

        {report && (
          <>
            {report.summary.trades === 0 && report.available_symbols.length === 0 && (
              <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-4 py-3 text-xs text-zinc-500">
                Sem histórico ainda. O collector no Windows envia as operações
                fechadas a cada ~5 minutos — deixe o MT5 aberto e logado.
              </div>
            )}

            <PerformanceKpis report={report} />
            <EquityCurveChart report={report} />

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

            <TradesTable report={report} />

            <p className="text-[11px] text-zinc-600">
              Fonte: histórico de negócios (deals) da própria corretora, lido pelo
              collector — o mesmo dinheiro que entrou na conta, já com comissão e
              swap. O saldo inicial de cada período vem do saldo atual da conta
              menos tudo que foi ganho desde então, então depósitos e saques não
              são separados. Datas e horas dos agrupamentos estão em UTC.
              {report.asof && ` Última leitura: ${new Date(report.asof).toLocaleString("pt-BR")}.`}
            </p>
          </>
        )}
      </main>
    </>
  );
}
