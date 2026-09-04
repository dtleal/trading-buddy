"use client";

import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtMoney, fmtPercent, fmtRatio, fmtSigned, netColor } from "@/lib/performance";
import type { PerformanceReport } from "@/lib/types";
import { cn } from "@/lib/utils";

type Period = "day" | "week" | "month";

const TABS: { key: Period; label: string }[] = [
  { key: "day", label: "Dia" },
  { key: "week", label: "Semana" },
  { key: "month", label: "Mês" },
];

/**
 * Result per day, per week or per month: how many trades, the hit rate, the
 * money made and the account balance at the end of each slice. Newest first.
 */
export function PeriodTable({ report }: { report: PerformanceReport }) {
  const [period, setPeriod] = useState<Period>("day");
  const buckets = {
    day: report.by_day,
    week: report.by_week,
    month: report.by_month,
  }[period];
  const cur = report.currency;
  const rows = [...buckets].reverse();

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Resultado por período</CardTitle>
            <CardDescription>fechamentos em UTC · mais recente primeiro</CardDescription>
          </div>
          <div className="flex gap-1">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setPeriod(tab.key)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  period === tab.key
                    ? "bg-sky-900 text-sky-200 ring-1 ring-sky-700/60"
                    : "bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-zinc-950/90 text-left text-[11px] uppercase tracking-wider text-zinc-500 backdrop-blur">
              <tr>
                <th className="px-2 py-1.5 font-medium">Período</th>
                <th className="px-2 py-1.5 text-right font-medium">Trades</th>
                <th className="px-2 py-1.5 text-right font-medium">Acerto</th>
                <th className="px-2 py-1.5 text-right font-medium">G/P</th>
                <th className="px-2 py-1.5 text-right font-medium">Fator</th>
                <th className="px-2 py-1.5 text-right font-medium">Resultado</th>
                <th className="px-2 py-1.5 text-right font-medium">Saldo no fim</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((bucket) => (
                <tr key={bucket.key} className="border-t border-zinc-900">
                  <td className="px-2 py-1.5 text-zinc-300">{bucket.label}</td>
                  <td className="px-2 py-1.5 text-right text-zinc-400">{bucket.stats.trades}</td>
                  <td className="px-2 py-1.5 text-right text-zinc-300">
                    {fmtPercent(bucket.stats.win_rate)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-zinc-500">
                    {bucket.stats.wins}/{bucket.stats.losses}
                  </td>
                  <td className="px-2 py-1.5 text-right text-zinc-400">
                    {fmtRatio(bucket.stats.profit_factor)}
                  </td>
                  <td
                    className={cn(
                      "px-2 py-1.5 text-right font-medium",
                      netColor(bucket.stats.net),
                    )}
                  >
                    {fmtSigned(bucket.stats.net, null)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-zinc-400">
                    {fmtMoney(bucket.balance_end, cur)}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-2 py-6 text-center text-zinc-600">
                    nenhum trade fechado nesse filtro
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
