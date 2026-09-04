"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtDateTime, fmtDuration, fmtSigned, netColor } from "@/lib/performance";
import type { PerformanceReport } from "@/lib/types";
import { cn, fmtPrice } from "@/lib/utils";

/**
 * Every closed trade of the selection, newest first: when it closed, the
 * asset, side, origin (hand-placed or the scalper bot), size, entry and exit
 * price, how long it was open and what it banked.
 */
export function TradesTable({ report }: { report: PerformanceReport }) {
  const rows = report.trades;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Operações</CardTitle>
        <CardDescription>
          {report.summary.trades} fechadas no filtro
          {report.trades_returned < report.summary.trades &&
            ` · mostrando as ${report.trades_returned} mais recentes`}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="max-h-[520px] overflow-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-zinc-950/90 text-left text-[11px] uppercase tracking-wider text-zinc-500 backdrop-blur">
              <tr>
                <th className="px-2 py-1.5 font-medium">Fechou</th>
                <th className="px-2 py-1.5 font-medium">Ativo</th>
                <th className="px-2 py-1.5 font-medium">Lado</th>
                <th className="px-2 py-1.5 font-medium">Origem</th>
                <th className="px-2 py-1.5 text-right font-medium">Lotes</th>
                <th className="px-2 py-1.5 text-right font-medium">Entrada</th>
                <th className="px-2 py-1.5 text-right font-medium">Saída</th>
                <th className="px-2 py-1.5 text-right font-medium">Tempo</th>
                <th className="px-2 py-1.5 text-right font-medium">Custos</th>
                <th className="px-2 py-1.5 text-right font-medium">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((trade) => (
                <tr key={trade.id} className="border-t border-zinc-900">
                  <td className="px-2 py-1.5 text-zinc-400">{fmtDateTime(trade.close_ts)}</td>
                  <td className="px-2 py-1.5 text-zinc-200">{trade.symbol}</td>
                  <td className="px-2 py-1.5">
                    <span
                      className={
                        trade.side === "buy" ? "text-emerald-400" : "text-red-400"
                      }
                    >
                      {trade.side === "buy" ? "compra" : "venda"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5">
                    <Badge tone={trade.source === "bot" ? "info" : "neutral"}>
                      {trade.source === "bot" ? "bot" : "manual"}
                    </Badge>
                  </td>
                  <td className="px-2 py-1.5 text-right text-zinc-400">
                    {trade.lots.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-zinc-400">
                    {fmtPrice(trade.open_price)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-zinc-400">
                    {fmtPrice(trade.close_price)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-zinc-500">
                    {fmtDuration(
                      (new Date(trade.close_ts).getTime() -
                        new Date(trade.open_ts).getTime()) /
                        1000,
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-right text-zinc-500">
                    {fmtSigned(trade.commission + trade.swap + trade.fee, null)}
                  </td>
                  <td className={cn("px-2 py-1.5 text-right font-medium", netColor(trade.net))}>
                    {fmtSigned(trade.net, null)}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-2 py-6 text-center text-zinc-600">
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
