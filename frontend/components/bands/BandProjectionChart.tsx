"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  LineStyle,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { computeBandProjection, type BandPoint } from "@/lib/bollinger";
import type { IntradayBar } from "@/lib/types";

const UP = "#10b981"; // emerald — up candles
const DOWN = "#ef4444"; // red — down candles
const BAND = "#60a5fa"; // blue-400 — upper/lower band
const MID = "#f59e0b"; // amber-500 — SMA20
const PROJ_PRICE = "#38bdf8"; // sky-400 — assumed close path

/** Projected bars ahead (6 × 5min = 30 min). */
const HORIZON = 6;
/** Real bars kept in view (the rest stay scrollable to the left). */
const VISIBLE_BARS = 42;

/**
 * One symbol's 5m candles with standard Bollinger (20, 2) plus the dashed
 * projected continuation of the three lines (see `lib/bollinger.ts` for what
 * the projection assumes). The sky dashed line is the assumed close path.
 */
export function BandProjectionChart({
  title,
  bars,
}: {
  title: string;
  bars: IntradayBar[];
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const linesRef = useRef<ISeriesApi<"Line">[]>([]);
  const lastBarTimeRef = useRef<number | null>(null);

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
    const candles = chart.addCandlestickSeries({
      upColor: UP,
      downColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      borderVisible: false,
    });
    const line = (color: string, style: LineStyle) =>
      chart.addLineSeries({
        color,
        lineWidth: 1,
        lineStyle: style,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    // Order matches the setData calls below: solid bands, dashed projections.
    linesRef.current = [
      line(BAND, LineStyle.Solid),
      line(MID, LineStyle.Solid),
      line(BAND, LineStyle.Solid),
      line(BAND, LineStyle.Dashed),
      line(MID, LineStyle.Dashed),
      line(BAND, LineStyle.Dashed),
      line(PROJ_PRICE, LineStyle.Dashed),
    ];
    chartRef.current = chart;
    candlesRef.current = candles;
    return () => {
      chart.remove();
      chartRef.current = null;
      candlesRef.current = null;
      linesRef.current = [];
      lastBarTimeRef.current = null;
    };
  }, []);

  // Push the polled bars + recompute bands/projection
  useEffect(() => {
    if (!candlesRef.current || bars.length === 0) return;
    const candleData: CandlestickData[] = bars.map((b) => ({
      time: sec(b.timestamp) as UTCTimestamp,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    candlesRef.current.setData(candleData);
    const proj = computeBandProjection(
      bars.map((b) => ({ time: sec(b.timestamp), close: b.close })),
      { horizon: HORIZON },
    );
    const datasets = [
      proj.upper,
      proj.mid,
      proj.lower,
      proj.projUpper,
      proj.projMid,
      proj.projLower,
      proj.projClose,
    ];
    linesRef.current.forEach((s, i) => s.setData(toLineData(datasets[i])));

    // Frame the last hours + the projection — but only when a NEW bar lands,
    // so the 5s forming-bar refresh doesn't fight the user's own zoom/scroll.
    const lastTime = candleData[candleData.length - 1].time as number;
    if (lastBarTimeRef.current !== lastTime) {
      lastBarTimeRef.current = lastTime;
      chartRef.current?.timeScale().setVisibleLogicalRange({
        from: candleData.length - VISIBLE_BARS,
        to: candleData.length + HORIZON + 1,
      });
    }
  }, [bars]);

  const last = bars.length > 0 ? bars[bars.length - 1].close : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-baseline justify-between">
          <CardTitle>{title}</CardTitle>
          {last !== null && (
            <span className="text-sm font-semibold tabular-nums text-zinc-100">
              {last.toLocaleString("en-US", { maximumFractionDigits: 2 })}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="relative w-full" style={{ height: 260 }}>
          <div ref={containerRef} className="absolute inset-0" />
          {bars.length === 0 && (
            <div className="absolute inset-0 grid place-items-center text-xs text-zinc-500">
              sem candles ainda — aguardando o collector
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function sec(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000);
}

function toLineData(points: BandPoint[]): LineData[] {
  return points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
}
