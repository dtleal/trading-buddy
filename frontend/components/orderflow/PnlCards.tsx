"use client";

import { Card } from "@/components/ui/card";
import { usePnl } from "@/hooks/usePnl";
import type { AccountPnl } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Three small cards at the top of the screen: realized account P&L for the
 * calendar day, week and month. Covers every closed trade (manual + bot) — it
 * comes from the broker's deal history, not just what the bot opened.
 */
const PERIODS: { key: keyof Pick<AccountPnl, "day" | "week" | "month">; label: string }[] = [
  { key: "day", label: "Hoje" },
  { key: "week", label: "Semana" },
  { key: "month", label: "Mês" },
];

/** Starting balance of the ActivTrades account, used for the monthly %. */
const INITIAL_CAPITAL_USD = 1000;

function fmtMoney(v: number, currency: string | null): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  const abs = Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${sign}${abs}${currency ? ` ${currency}` : ""}`;
}

/** P&L as a share of the starting balance, e.g. +3.50%. */
function fmtPct(v: number): string {
  const pct = (v / INITIAL_CAPITAL_USD) * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "";
  return `${sign}${Math.abs(pct).toFixed(2)}%`;
}

function tone(v: number): string {
  if (v > 0) return "text-emerald-400";
  if (v < 0) return "text-red-400";
  return "text-zinc-300";
}

export function PnlCards() {
  const pnl = usePnl();

  return (
    <div className="grid grid-cols-3 gap-3">
      {PERIODS.map(({ key, label }) => {
        const value = pnl?.[key] ?? 0;
        return (
          <Card key={key} className="px-4 py-3">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              {label}
            </div>
            <div
              className={cn(
                "mt-1 text-2xl font-semibold tabular-nums",
                pnl ? tone(value) : "text-zinc-600",
              )}
            >
              {pnl ? fmtMoney(value, pnl.currency) : "—"}
            </div>
            {key === "month" && (
              <div className={cn("text-[11px] tabular-nums", pnl ? tone(value) : "text-zinc-600")}>
                {pnl ? fmtPct(value) : "—"}
                <span className="ml-1 text-zinc-500">do capital inicial</span>
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
