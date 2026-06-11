"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createChart,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";
import { api } from "@/lib/api";
import type { IntradayBar } from "@/lib/types";

const REGIME_LOW = 15;   // below = "calm"
const REGIME_HIGH = 25;  // above = "stress"

/**
 * VIX line chart with regime guide-lines at 15 and 25.
 *
 * Initial bars come from REST (TanStack Query). The chart subscribes to a
 * `liveVix` prop (the latest VIX read from the WS) and appends/updates the
 * most recent point as it changes.
 */
export function VixChart({
  liveVix,
  height = 360,
}: {
  liveVix: number | null;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const { data, error, isLoading } = useQuery({
    queryKey: ["vix-history"],
    queryFn: () => api.getVixHistory(2),
    staleTime: 60_000,
  });

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

    const series = chart.addLineSeries({
      color: "#38bdf8",
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });

    series.createPriceLine({
      price: REGIME_LOW,
      color: "#10b981",
      lineStyle: 2,
      lineWidth: 1,
      axisLabelVisible: true,
      title: "calm 15",
    });
    series.createPriceLine({
      price: REGIME_HIGH,
      color: "#ef4444",
      lineStyle: 2,
      lineWidth: 1,
      axisLabelVisible: true,
      title: "stress 25",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Push REST history into the chart
  useEffect(() => {
    if (!seriesRef.current || !data) return;
    const points = barsToLineData(data.bars);
    seriesRef.current.setData(points);
    chartRef.current?.timeScale().fitContent();
  }, [data]);

  // Live update from the WS feed — patch the latest bar with the current VIX
  useEffect(() => {
    if (!seriesRef.current || liveVix === null) return;
    const now = (Math.floor(Date.now() / 1000)) as UTCTimestamp;
    seriesRef.current.update({ time: now, value: liveVix });
  }, [liveVix]);

  if (error) {
    return (
      <div className="rounded-md border border-red-900/50 bg-red-950/30 p-4 text-sm text-red-300">
        Falha ao carregar histórico do VIX:{" "}
        {error instanceof Error ? error.message : "erro desconhecido"}
      </div>
    );
  }

  return (
    <div className="relative w-full" style={{ height }}>
      <div ref={containerRef} className="absolute inset-0" />
      {isLoading && (
        <div className="absolute inset-0 grid place-items-center text-xs text-zinc-500">
          carregando barras…
        </div>
      )}
    </div>
  );
}

function barsToLineData(bars: IntradayBar[]): LineData[] {
  return bars.map((b) => ({
    time: (Math.floor(new Date(b.timestamp).getTime() / 1000)) as UTCTimestamp,
    value: b.close,
  }));
}
