"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  LineType,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useBalanceHistory } from "@/hooks/useBalanceHistory";
import type { AccountBalanceHistory, BalanceStep } from "@/lib/types";
import { chartColors, useTheme } from "@/lib/theme";

const UP_LINE = "#10b981"; // emerald — above opening balance (profit)
const DOWN_LINE = "#ef4444"; // red — below opening balance (loss)

/**
 * Account P&L area chart, styled like the VIX chart: a single value curve
 * (realized balance per trade from the broker deal history, tipped with live
 * equity) drawn as a baseline area — green fill above the period's opening
 * balance, red below — with a dashed guide-line at that opening. Reads at a
 * glance as "up or down on the account". Polled from the balance endpoint.
 */
export function AccountBalanceCard() {
  const history = useBalanceHistory();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const theme = useTheme();
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Baseline"> | null>(null);
  const openLineRef = useRef<IPriceLine | null>(null);

  // Init chart once
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#a1a1aa",
        fontFamily: "var(--font-sans), system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: "rgba(63,63,70,0.4)" },
        horzLines: { color: "rgba(63,63,70,0.4)" },
      },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#27272a" },
      rightPriceScale: { borderColor: "#27272a" },
      crosshair: { mode: 1 },
    });
    const series = chart.addBaselineSeries({
      baseValue: { type: "price", price: 0 },
      topLineColor: UP_LINE,
      topFillColor1: "rgba(16,185,129,0.28)",
      topFillColor2: "rgba(16,185,129,0.04)",
      bottomLineColor: DOWN_LINE,
      bottomFillColor1: "rgba(239,68,68,0.04)",
      bottomFillColor2: "rgba(239,68,68,0.28)",
      lineWidth: 2,
      lineType: LineType.WithSteps, // one step per closed trade
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    openLineRef.current = series.createPriceLine({
      price: 0,
      color: "#71717a",
      lineStyle: 2,
      lineWidth: 1,
      axisLabelVisible: true,
      title: "abertura",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      openLineRef.current = null;
    };
  }, []);

  // Repaint the axes/grid when the dark/light toggle flips.
  useEffect(() => {
    const c = chartColors(theme);
    chartRef.current?.applyOptions({
      layout: { textColor: c.text },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      timeScale: { borderColor: c.border },
      rightPriceScale: { borderColor: c.border },
    });
  }, [theme]);

  // Push the polled data + reposition the baseline / opening guide
  useEffect(() => {
    if (!seriesRef.current || !history) return;
    const opening = openingBalance(history);
    seriesRef.current.applyOptions({ baseValue: { type: "price", price: opening } });
    openLineRef.current?.applyOptions({ price: opening });
    seriesRef.current.setData(buildCurve(history));
    chartRef.current?.timeScale().fitContent();
  }, [history]);

  const cur = history?.currency ?? null;
  const equity = history?.equity ?? null;
  const balance = history?.balance ?? null;
  const opening = history ? openingBalance(history) : null;
  const floating = equity !== null && balance !== null ? equity - balance : null;
  const period = equity !== null && opening !== null ? equity - opening : null;
  const hasData =
    !!history && (history.balance_steps.length > 0 || history.equity_points.length > 0);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Saldo da conta</CardTitle>
            <CardDescription>
              valor da conta vs abertura · verde acima (lucro) / vermelho abaixo
            </CardDescription>
          </div>
          {equity !== null && (
            <div className="flex items-baseline gap-3">
              <span className="text-3xl font-semibold tabular-nums text-zinc-100">
                {fmtMoney(equity, cur)}
              </span>
              <div className="flex flex-wrap gap-2">
                {period !== null && (
                  <Badge tone={period > 0 ? "positive" : period < 0 ? "negative" : "neutral"}>
                    {fmtSigned(period, cur)}
                  </Badge>
                )}
                {floating !== null && (
                  <Badge tone={floating > 0 ? "positive" : floating < 0 ? "negative" : "neutral"}>
                    flutuante {fmtSigned(floating, null)}
                  </Badge>
                )}
              </div>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="relative w-full" style={{ height: 200 }}>
          <div ref={containerRef} className="absolute inset-0" />
          {!history && (
            <div className="absolute inset-0 grid place-items-center text-xs text-zinc-500">
              carregando saldo…
            </div>
          )}
          {history && !hasData && (
            <div className="absolute inset-0 grid place-items-center text-xs text-zinc-500">
              sem dados de saldo ainda — aguardando o collector
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/** Balance before the first deal of the window = the period's opening balance
 * (the baseline the area fills against). Falls back to the current balance. */
function openingBalance(h: AccountBalanceHistory): number {
  const first: BalanceStep | undefined = h.balance_steps[0];
  if (first) return first.balance - first.pnl;
  return h.balance;
}

/** The account-value curve: realized balance per trade, tipped with the live
 * equity so the last segment shows floating P&L. Deduped to unique seconds. */
function buildCurve(h: AccountBalanceHistory): LineData[] {
  const byTime = new Map<number, number>();
  for (const s of h.balance_steps) byTime.set(sec(s.ts), s.balance);
  if (h.asof != null) byTime.set(sec(h.asof), h.equity);
  return [...byTime.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([t, value]) => ({ time: t as UTCTimestamp, value }));
}

function sec(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000);
}

function fmtMoney(v: number, currency: string | null): string {
  const abs = v.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${abs}${currency ? ` ${currency}` : ""}`;
}

function fmtSigned(v: number, currency: string | null): string {
  const sign = v > 0 ? "+" : v < 0 ? "−" : "";
  return `${sign}${fmtMoney(Math.abs(v), currency)}`;
}
