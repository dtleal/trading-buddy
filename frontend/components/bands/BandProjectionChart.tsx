"use client";

import { useEffect, useMemo, useRef } from "react";
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
import { computeBands, type BandPoint } from "@/lib/bollinger";
import { ZonesPrimitive } from "@/lib/chartZones";
import { BandOddsBadges } from "./BandOddsBadges";
import { PressureGauge } from "@/components/orderflow/PressureGauge";
import type {
  BandRegime,
  BandScenario,
  IntradayBar,
  OrderFlowSnapshot,
  PriceZone,
} from "@/lib/types";
import { chartColors, useTheme } from "@/lib/theme";

const UP = "#10b981"; // emerald — up candles
const DOWN = "#ef4444"; // red — down candles
const BAND = "#60a5fa"; // blue-400 — upper/lower band
const MID = "#f59e0b"; // amber-500 — SMA20

/** Real bars kept in view; the rest stay scrollable to the left. */
const VISIBLE_BARS = 40;

/** How far past the visible candles a zone may sit and still be drawn, as a
 * multiple of the visible high-low range. Scales itself: a quiet chart shows
 * only the zones right there, a wide-range one reaches further. Zones beyond
 * this would squash the candles into a sliver (the price scale stretches to
 * fit them) for a level price cannot reach today anyway. */
const ZONE_REACH = 1.0;

/**
 * One symbol's 5m candles with standard Bollinger (20, 2) and the price zones
 * shaded behind them. Nothing else on purpose: the chart is read for where
 * price sits inside the bands and which region it is walking into.
 */
export function BandProjectionChart({
  title,
  bars,
  scenario,
  flow,
  zones,
}: {
  title: string;
  bars: IntradayBar[];
  scenario?: BandScenario;
  flow?: OrderFlowSnapshot;
  /** Price zones for this symbol; the near ones are shaded on the chart. */
  zones?: PriceZone[];
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const theme = useTheme();
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const linesRef = useRef<ISeriesApi<"Line">[]>([]);
  const zonesRef = useRef<ZonesPrimitive | null>(null);
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
    const line = (color: string) =>
      chart.addLineSeries({
        color,
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    // Order matches the datasets pushed below.
    linesRef.current = [line(BAND), line(MID), line(BAND)];
    // Shaded buy/sell zones, drawn under the candles.
    const zonePrimitive = new ZonesPrimitive();
    candles.attachPrimitive(zonePrimitive);
    zonesRef.current = zonePrimitive;
    chartRef.current = chart;
    candlesRef.current = candles;
    return () => {
      chart.remove();
      chartRef.current = null;
      candlesRef.current = null;
      linesRef.current = [];
      zonesRef.current = null;
      lastBarTimeRef.current = null;
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

  // Push the polled bars + recompute the bands
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

    const bands = computeBands(bars.map((b) => ({ time: sec(b.timestamp), close: b.close })));
    const datasets = [bands.upper, bands.mid, bands.lower];
    linesRef.current.forEach((s, i) => s.setData(toLineData(datasets[i])));

    // Frame the last hours — but only when a NEW bar lands, so the 5s
    // forming-bar refresh doesn't fight the user's own zoom/scroll.
    const lastTime = candleData[candleData.length - 1].time as number;
    if (lastBarTimeRef.current !== lastTime) {
      lastBarTimeRef.current = lastTime;
      chartRef.current?.timeScale().setVisibleLogicalRange({
        from: candleData.length - VISIBLE_BARS,
        to: candleData.length + 1,
      });
    }
  }, [bars]);

  // Zones near enough to matter for this chart's view. The rest are real
  // levels, just not ones today's candles are anywhere near.
  const nearZones = useMemo(() => {
    if (!zones?.length || bars.length === 0) return [];
    const view = bars.slice(-VISIBLE_BARS);
    const hi = Math.max(...view.map((b) => b.high));
    const lo = Math.min(...view.map((b) => b.low));
    const reach = (hi - lo) * ZONE_REACH;
    return zones.filter((z) => z.low <= hi + reach && z.high >= lo - reach);
  }, [zones, bars]);

  useEffect(() => {
    zonesRef.current?.setZones(nearZones);
  }, [nearZones]);

  const last = bars.length > 0 ? bars[bars.length - 1].close : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{title}</CardTitle>
            <BandOddsBadges scenario={scenario} closes={bars.map((b) => b.close)} />
          </div>
          {/* Live buy/sell pressure — the tape's lean right now, next to the
              historical lean the badge carries. */}
          <div className="w-32 shrink-0 sm:w-40" title="pressão compradora · vendedora (tape ao vivo)">
            <PressureGauge flow={flow} />
          </div>
          {last !== null && (
            <span className="text-sm font-semibold tabular-nums text-zinc-100">
              {last.toLocaleString("en-US", { maximumFractionDigits: 2 })}
            </span>
          )}
        </div>
        {scenario?.regime && <RegimeChips regime={scenario.regime} />}
      </CardHeader>
      <CardContent>
        <div className="relative w-full" style={{ height: 440 }}>
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

const TREND_LABEL = {
  up: "tendência de alta",
  flat: "sem tendência",
  down: "tendência de baixa",
} as const;
const WIDTH_LABEL = {
  expanding: "bandas alargando",
  steady: "largura normal",
  squeezing: "bandas apertando",
} as const;
const PUSH_LABEL = { up: "candle grande ↑", down: "candle grande ↓", none: "" } as const;

/** The market state the numbers below are conditioned on. Amber marks the
 * states that work AGAINST a return to the middle (bands opening up, one
 * outsized candle driving). */
function RegimeChips({ regime }: { regime: BandRegime }) {
  const chip = (text: string, tone: string) => (
    <span key={text} className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${tone}`}>
      {text}
    </span>
  );
  return (
    <div className="flex flex-wrap items-center gap-1">
      {chip(
        TREND_LABEL[regime.trend],
        regime.trend === "up"
          ? "bg-emerald-500/10 text-emerald-400"
          : regime.trend === "down"
            ? "bg-red-500/10 text-red-400"
            : "bg-zinc-800 text-zinc-400",
      )}
      {chip(
        WIDTH_LABEL[regime.width],
        regime.width === "expanding"
          ? "bg-amber-500/10 text-amber-400"
          : regime.width === "squeezing"
            ? "bg-sky-500/10 text-sky-400"
            : "bg-zinc-800 text-zinc-400",
      )}
      {regime.push !== "none" &&
        chip(PUSH_LABEL[regime.push], "bg-amber-500/10 text-amber-400")}
    </div>
  );
}

function sec(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000);
}

function toLineData(points: BandPoint[]): LineData[] {
  return points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
}
