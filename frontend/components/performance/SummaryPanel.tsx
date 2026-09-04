"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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

/** One "label ....... value" line, the way the Profit report lists them. */
function Row({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-zinc-900 py-1.5">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className={cn("text-xs font-medium tabular-nums", tone ?? "text-zinc-200")}>
        {value}
      </span>
    </div>
  );
}

/**
 * The full stat list, laid out like the "Resumo" tab of the Profit (Nelogica)
 * performance report and using its names, so the numbers read the same as the
 * report the trader already knows.
 */
export function SummaryPanel({ report }: { report: PerformanceReport }) {
  const s = report.summary;
  const cur = report.currency;
  const costs = s.commission + s.swap;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Resumo</CardTitle>
        <CardDescription>
          mesmas contas do Relatório de Performance do Profit, sobre as operações
          fechadas do filtro
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-x-8 md:grid-cols-2 xl:grid-cols-3">
        <div>
          <div className="pb-1 text-[11px] uppercase tracking-wider text-zinc-600">
            Resultado
          </div>
          <Row
            label="Saldo líquido total"
            value={fmtSigned(s.net, cur)}
            tone={netColor(s.net)}
          />
          <Row label="Lucro bruto" value={fmtMoney(s.gross_profit, cur)} tone="text-emerald-400" />
          <Row label="Prejuízo bruto" value={fmtMoney(-s.gross_loss, cur)} tone="text-red-400" />
          <Row label="Fator de lucro" value={fmtRatio(s.profit_factor)} />
          <Row
            label="Custos (comissão + swap)"
            value={fmtSigned(costs, cur)}
            tone={costs < 0 ? "text-red-400" : undefined}
          />
          <Row label="Resultado médio por operação" value={fmtSigned(s.expectancy, cur)} />
          <Row label="Volume total" value={`${s.lots.toFixed(2)} lotes`} />
        </div>

        <div>
          <div className="pb-1 text-[11px] uppercase tracking-wider text-zinc-600">
            Operações
          </div>
          <Row label="Total de operações" value={String(s.trades)} />
          <Row
            label="Operações vencedoras"
            value={`${s.wins} (${fmtPercent(s.win_rate)})`}
            tone="text-emerald-400"
          />
          <Row
            label="Operações perdedoras"
            value={`${s.losses} (${fmtPercent(s.loss_rate)})`}
            tone="text-red-400"
          />
          <Row label="Operações zeradas" value={String(s.breakeven)} />
          <Row label="Média das vencedoras" value={fmtMoney(s.avg_win, cur)} />
          <Row label="Média das perdedoras" value={fmtMoney(-s.avg_loss, cur)} />
          <Row label="Razão média lucro : média prejuízo" value={fmtRatio(s.payoff)} />
          <Row label="Maior ganho" value={fmtSigned(s.best, cur)} tone="text-emerald-400" />
          <Row label="Maior perda" value={fmtSigned(s.worst, cur)} tone="text-red-400" />
          <Row
            label="Sequência máxima (ganhos / perdas)"
            value={`${s.max_consecutive_wins} / ${s.max_consecutive_losses}`}
          />
        </div>

        <div>
          <div className="pb-1 text-[11px] uppercase tracking-wider text-zinc-600">
            Conta e tempo
          </div>
          <Row label="Saldo no início do período" value={fmtMoney(report.start_balance, cur)} />
          <Row label="Depósitos no período" value={fmtSigned(report.deposits, cur)} />
          <Row label="Saques no período" value={fmtSigned(-report.withdrawals, cur)} />
          <Row label="Capital (início + depósitos)" value={fmtMoney(report.capital, cur)} />
          <Row label="Saldo atual" value={fmtMoney(report.end_balance, cur)} />
          <Row label="Patrimônio máximo" value={fmtMoney(report.peak_balance, cur)} />
          <Row
            label="Retorno sobre o capital"
            value={fmtSignedPercent(report.return_pct)}
            tone={netColor(report.return_pct)}
          />
          <Row
            label="Máximo drawdown"
            value={`${fmtMoney(report.max_drawdown, cur)} (${fmtPercent(
              report.max_drawdown_pct,
              2,
            )})`}
            tone={report.max_drawdown > 0 ? "text-red-400" : undefined}
          />
          <Row
            label="Drawdown atual"
            value={`${fmtMoney(report.current_drawdown, cur)} (${fmtPercent(
              report.current_drawdown_pct,
              2,
            )})`}
          />
          <Row label="Fator de recuperação" value={fmtRatio(report.recovery_factor)} />
          <Row label="Tempo médio em operação" value={fmtDuration(s.avg_duration_seconds)} />
          <Row
            label="Tempo médio das vencedoras"
            value={fmtDuration(s.avg_win_duration_seconds)}
          />
          <Row
            label="Tempo médio das perdedoras"
            value={fmtDuration(s.avg_loss_duration_seconds)}
            tone={
              s.avg_loss_duration_seconds > 2 * s.avg_win_duration_seconds &&
              s.avg_win_duration_seconds > 0
                ? "text-amber-400"
                : undefined
            }
          />
          <Row
            label="TET (tempo entre operações)"
            value={fmtDuration(report.avg_time_between_trades_seconds)}
          />
        </div>
      </CardContent>
    </Card>
  );
}
