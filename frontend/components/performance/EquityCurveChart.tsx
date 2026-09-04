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
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { chartColors, useTheme } from "@/lib/theme";
import { fmtMoney, fmtPercent, fmtSigned, fmtSignedPercent } from "@/lib/performance";
import type { EquityCurvePoint, PerformanceReport } from "@/lib/types";

const UP_LINE = "#10b981"; // emerald — above the period's opening balance
const DOWN_LINE = "#ef4444"; // red — below it
const DD_LINE = "#f59e0b"; // amber — the drawdown curve

/**
 * Equity evolution of the selected trades: the account balance after each
 * closed trade, drawn against the balance the period started from (green fill
 * above, red below), plus a second chart with how far below its own peak the
 * account was at each point ("drawdown", in %).
 *
 * Both read the same `equity_curve` the backend computes, so the numbers in
 * the KPI cards and the shapes here can never disagree.
 */
export function EquityCurveChart({ report }: { report: PerformanceReport }) {
  const theme = useTheme();
  const balanceRef = useRef<HTMLDivElement | null>(null);
  const ddRef = useRef<HTMLDivElement | null>(null);
  const balanceChart = useRef<IChartApi | null>(null);
  const ddChart = useRef<IChartApi | null>(null);
  const balanceSeries = useRef<ISeriesApi<"Baseline"> | null>(null);
  const ddSeries = useRef<ISeriesApi<"Area"> | null>(null);
  const openLine = useRef<IPriceLine | null>(null);

  // Init both charts once.
  useEffect(() => {
    if (!balanceRef.current || !ddRef.current) return;
    const common = {
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
      crosshair: { mode: 1 as const },
    };
    const bChart = createChart(balanceRef.current, common);
    const bSeries = bChart.addBaselineSeries({
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
    openLine.current = bSeries.createPriceLine({
      price: 0,
      color: "#71717a",
      lineStyle: 2,
      lineWidth: 1,
      axisLabelVisible: true,
      title: "início",
    });
    const dChart = createChart(ddRef.current, common);
    const dSeries = dChart.addAreaSeries({
      lineColor: DD_LINE,
      topColor: "rgba(245,158,11,0.35)",
      bottomColor: "rgba(245,158,11,0.02)",
      lineWidth: 2,
      lineType: LineType.WithSteps,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
      invertFilledArea: true, // drawdown hangs down from zero
    });
    balanceChart.current = bChart;
    ddChart.current = dChart;
    balanceSeries.current = bSeries;
    ddSeries.current = dSeries;
    return () => {
      bChart.remove();
      dChart.remove();
      balanceChart.current = null;
      ddChart.current = null;
      balanceSeries.current = null;
      ddSeries.current = null;
      openLine.current = null;
    };
  }, []);

  // Repaint the axes/grid when the dark/light toggle flips.
  useEffect(() => {
    const c = chartColors(theme);
    for (const chart of [balanceChart.current, ddChart.current]) {
      chart?.applyOptions({
        layout: { textColor: c.text },
        grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
        timeScale: { borderColor: c.border },
        rightPriceScale: { borderColor: c.border },
      });
    }
  }, [theme]);

  // Feed the report in.
  useEffect(() => {
    if (!balanceSeries.current || !ddSeries.current) return;
    const start = report.start_balance;
    balanceSeries.current.applyOptions({ baseValue: { type: "price", price: start } });
    openLine.current?.applyOptions({ price: start });
    balanceSeries.current.setData(curve(report.equity_curve, start));
    ddSeries.current.setData(drawdownCurve(report.equity_curve));
    balanceChart.current?.timeScale().fitContent();
    ddChart.current?.timeScale().fitContent();
  }, [report]);

  const cur = report.currency;
  const empty = report.equity_curve.length === 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle>Evolução patrimonial</CardTitle>
            <CardDescription>
              saldo da conta a cada trade fechado · verde acima do início, vermelho abaixo
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="text-2xl font-semibold tabular-nums text-zinc-100">
              {fmtMoney(report.end_balance, cur)}
            </span>
            <Badge
              tone={
                report.summary.net > 0
                  ? "positive"
                  : report.summary.net < 0
                    ? "negative"
                    : "neutral"
              }
            >
              {fmtSigned(report.summary.net, cur)} ({fmtSignedPercent(report.return_pct)})
            </Badge>
            <Badge tone={report.max_drawdown > 0 ? "warning" : "neutral"}>
              DD máx {fmtMoney(report.max_drawdown, cur)} ({fmtPercent(report.max_drawdown_pct, 2)})
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="relative w-full" style={{ height: 260 }}>
          <div ref={balanceRef} className="absolute inset-0" />
          {empty && (
            <div className="absolute inset-0 grid place-items-center text-xs text-zinc-500">
              nenhum trade fechado nesse filtro
            </div>
          )}
        </div>
        <div className="text-[11px] uppercase tracking-wider text-zinc-500">
          Drawdown (% abaixo do topo da conta)
        </div>
        <div className="relative w-full" style={{ height: 110 }}>
          <div ref={ddRef} className="absolute inset-0" />
        </div>
      </CardContent>
    </Card>
  );
}

/** Balance steps, prefixed with the period's opening balance so the curve
 * starts at the account's real value. Deduped to unique seconds (two trades
 * closed in the same second would otherwise be rejected by the chart). */
function curve(points: EquityCurvePoint[], start: number): LineData[] {
  if (points.length === 0) return [];
  const byTime = new Map<number, number>();
  byTime.set(sec(points[0].ts) - 1, start);
  for (const p of points) byTime.set(sec(p.ts), p.balance);
  return toLine(byTime);
}

/** Drawdown as a negative percentage, so the area hangs below zero. */
function drawdownCurve(points: EquityCurvePoint[]): LineData[] {
  if (points.length === 0) return [];
  const byTime = new Map<number, number>();
  byTime.set(sec(points[0].ts) - 1, 0);
  for (const p of points) byTime.set(sec(p.ts), -p.drawdown_pct);
  return toLine(byTime);
}

function toLine(byTime: Map<number, number>): LineData[] {
  return [...byTime.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
}

function sec(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000);
}
