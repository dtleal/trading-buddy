"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtPercent, fmtRatio, fmtSigned, netColor } from "@/lib/performance";
import type { PerformanceGroup } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * A small breakdown table — one row per asset, origin (manual vs bot), side,
 * weekday or hour of day — so it's easy to see where the money actually comes
 * from. Reused for all five cuts.
 */
export function BreakdownTable({
  title,
  description,
  rows,
}: {
  title: string;
  description?: string;
  rows: PerformanceGroup[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>
        <table className="w-full text-xs tabular-nums">
          <thead className="text-left text-[11px] uppercase tracking-wider text-zinc-500">
            <tr>
              <th className="px-2 py-1 font-medium">&nbsp;</th>
              <th className="px-2 py-1 text-right font-medium">Trades</th>
              <th className="px-2 py-1 text-right font-medium">Acerto</th>
              <th className="px-2 py-1 text-right font-medium">Fator</th>
              <th className="px-2 py-1 text-right font-medium">Resultado</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-t border-zinc-900">
                <td className="px-2 py-1.5 text-zinc-300">{row.label}</td>
                <td className="px-2 py-1.5 text-right text-zinc-400">{row.stats.trades}</td>
                <td className="px-2 py-1.5 text-right text-zinc-300">
                  {fmtPercent(row.stats.win_rate)}
                </td>
                <td className="px-2 py-1.5 text-right text-zinc-400">
                  {fmtRatio(row.stats.profit_factor)}
                </td>
                <td className={cn("px-2 py-1.5 text-right font-medium", netColor(row.stats.net))}>
                  {fmtSigned(row.stats.net, null)}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-2 py-4 text-center text-zinc-600">
                  sem dados
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
