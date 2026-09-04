"use client";

import { Card, CardContent } from "@/components/ui/card";
import {
  fmtMoney,
  fmtPercent,
  fmtRatio,
  fmtSigned,
  fmtSignedPercent,
  netColor,
} from "@/lib/performance";
import type { PerformanceReport } from "@/lib/types";
import { cn } from "@/lib/utils";

/** One number with its name and a one-line explanation under it. */
function Kpi({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
        <div className={cn("mt-1 text-xl font-semibold tabular-nums", tone ?? "text-zinc-100")}>
          {value}
        </div>
        {hint && <div className="mt-0.5 text-[11px] text-zinc-500">{hint}</div>}
      </CardContent>
    </Card>
  );
}

/**
 * The headline numbers, named like the Profit performance report: what the
 * trading made, how often it hit, how much it won per dollar lost, the payoff,
 * the worst fall and the return over the capital. The full stat list lives in
 * `SummaryPanel`.
 */
export function PerformanceKpis({ report }: { report: PerformanceReport }) {
  const s = report.summary;
  const cur = report.currency;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Kpi
        label="Saldo líquido total"
        value={fmtSigned(s.net, cur)}
        hint={`${s.trades} operações · ${fmtSigned(s.expectancy, null)} por operação`}
        tone={netColor(s.net)}
      />
      <Kpi
        label="Operações vencedoras"
        value={fmtPercent(s.win_rate)}
        hint={`${s.wins} ganhos · ${s.losses} perdas${
          s.breakeven > 0 ? ` · ${s.breakeven} zeradas` : ""
        }`}
      />
      <Kpi
        label="Fator de lucro"
        value={fmtRatio(s.profit_factor)}
        hint={`${fmtMoney(s.gross_profit, null)} ganhos ÷ ${fmtMoney(s.gross_loss, null)} perdas`}
        tone={
          s.profit_factor === null
            ? undefined
            : s.profit_factor >= 1
              ? "text-emerald-400"
              : "text-red-400"
        }
      />
      <Kpi
        label="Razão média lucro : prejuízo"
        value={fmtRatio(s.payoff)}
        hint={`média ganho ${fmtMoney(s.avg_win, null)} · média perda ${fmtMoney(
          s.avg_loss,
          null,
        )}`}
      />
      <Kpi
        label="Máximo drawdown"
        value={fmtMoney(report.max_drawdown, cur)}
        hint={`${fmtPercent(report.max_drawdown_pct, 2)} do patrimônio máximo`}
        tone={report.max_drawdown > 0 ? "text-red-400" : undefined}
      />
      <Kpi
        label="Retorno sobre o capital"
        value={fmtSignedPercent(report.return_pct)}
        hint={
          report.deposits > 0
            ? `capital ${fmtMoney(report.capital, cur)} (inclui ${fmtMoney(
                report.deposits,
                null,
              )} depositados)`
            : `capital ${fmtMoney(report.capital, cur)}`
        }
        tone={netColor(report.return_pct)}
      />
    </div>
  );
}
