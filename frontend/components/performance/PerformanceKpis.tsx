"use client";

import { Card, CardContent } from "@/components/ui/card";
import {
  fmtDuration,
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
 * The headline numbers of the selected period: result, hit rate, the win/loss
 * split, profit factor, payoff (risk-return in money), expectancy per trade,
 * drawdown in money and %, return over the account and recovery factor.
 */
export function PerformanceKpis({ report }: { report: PerformanceReport }) {
  const s = report.summary;
  const cur = report.currency;

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Kpi
        label="Resultado"
        value={fmtSigned(s.net, cur)}
        hint={`${s.trades} operações fechadas`}
        tone={netColor(s.net)}
      />
      <Kpi
        label="Taxa de acerto"
        value={fmtPercent(s.win_rate)}
        hint={`${s.wins} ganhos · ${s.losses} perdas${
          s.breakeven > 0 ? ` · ${s.breakeven} zerados` : ""
        }`}
      />
      <Kpi
        label="Perdedoras"
        value={fmtPercent(s.loss_rate)}
        hint={`média das perdas ${fmtMoney(s.avg_loss, cur)}`}
        tone={s.loss_rate > 50 ? "text-red-400" : undefined}
      />
      <Kpi
        label="Fator de lucro"
        value={fmtRatio(s.profit_factor)}
        hint={`ganhou ${fmtMoney(s.gross_profit, cur)} · perdeu ${fmtMoney(s.gross_loss, cur)}`}
        tone={
          s.profit_factor === null
            ? undefined
            : s.profit_factor >= 1
              ? "text-emerald-400"
              : "text-red-400"
        }
      />
      <Kpi
        label="Risco × retorno"
        value={fmtRatio(s.payoff)}
        hint={`ganho médio ${fmtMoney(s.avg_win, cur)} ÷ perda média ${fmtMoney(s.avg_loss, cur)}`}
      />
      <Kpi
        label="Por operação"
        value={fmtSigned(s.expectancy, cur)}
        hint={`esperado por trade · ${fmtDuration(s.avg_duration_seconds)} em média`}
        tone={netColor(s.expectancy)}
      />
      <Kpi
        label="Drawdown máximo"
        value={fmtMoney(report.max_drawdown, cur)}
        hint={`${fmtPercent(report.max_drawdown_pct, 2)} do topo da conta`}
        tone={report.max_drawdown > 0 ? "text-red-400" : undefined}
      />
      <Kpi
        label="Drawdown agora"
        value={fmtMoney(report.current_drawdown, cur)}
        hint={`${fmtPercent(report.current_drawdown_pct, 2)} abaixo do topo`}
        tone={report.current_drawdown > 0 ? "text-amber-400" : "text-emerald-400"}
      />
      <Kpi
        label="Retorno"
        value={fmtSignedPercent(report.return_pct)}
        hint={`de ${fmtMoney(report.start_balance, cur)} para ${fmtMoney(report.end_balance, cur)}`}
        tone={netColor(report.return_pct)}
      />
      <Kpi
        label="Recuperação"
        value={fmtRatio(report.recovery_factor)}
        hint="resultado ÷ drawdown máximo"
      />
      <Kpi
        label="Sequências"
        value={`${s.max_consecutive_wins} × ${s.max_consecutive_losses}`}
        hint="maior sequência de ganhos × de perdas"
      />
      <Kpi
        label="Custos e volume"
        value={fmtSigned(s.commission + s.swap, cur)}
        hint={`comissão + swap · ${s.lots.toFixed(2)} lotes negociados`}
        tone={s.commission + s.swap < 0 ? "text-red-400" : undefined}
      />
    </div>
  );
}
