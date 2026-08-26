"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  LineStyle,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
  type WhitespaceData,
} from "lightweight-charts";
import { Crosshair, Route } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { computeBandProjection, type BandPoint } from "@/lib/bollinger";
import {
  gradedWindows,
  loadHistory,
  saveHistory,
  scoreForecast,
  scoreRoute,
  updateHistory,
  type BandForecast,
  type ForecastScore,
  type RouteScore,
} from "@/lib/bandForecast";
import { BandOddsBadges } from "./BandOddsBadges";
import { PressureGauge } from "@/components/orderflow/PressureGauge";
import type { BandRegime, BandScenario, IntradayBar, OrderFlowSnapshot } from "@/lib/types";
import { chartColors, useTheme } from "@/lib/theme";

const UP = "#10b981"; // emerald — up candles
const DOWN = "#ef4444"; // red — down candles
const BAND = "#60a5fa"; // blue-400 — upper/lower band
const MID = "#f59e0b"; // amber-500 — SMA20
const ROUTE = "#38bdf8"; // sky-400 — the measured route ahead
const PAST = "#c084fc"; // purple-400 — the frozen bands being graded
const PAST_ROUTE = "#e879f9"; // fuchsia-400 — the frozen price route being graded

/** Bars ahead when there is no measured route to follow (6 × 5min = 30 min). */
const FALLBACK_HORIZON = 6;
/** Real bars kept in view (the rest stay scrollable to the left). Kept tight on
 * purpose: with the graded windows covering the last ~20 candles, packing more
 * bars in only makes the lines overlap. */
const VISIBLE_BARS = 40;

/**
 * One symbol's 5m candles with standard Bollinger (20, 2), the route price
 * usually took from here, and the bands' continuation under that same route.
 *
 * The route (sky, dashed) comes from the backend: every past bar where price
 * sat at this same spot inside the band, and what happened next. No measured
 * route (thin sample / cold start) → the bands fall back to a drift
 * extrapolation and no route is drawn.
 *
 * The last projection is also FROZEN (purple) and left pinned to its own
 * timestamps while the real candles fill in over it, so the forecast can be
 * compared with the bands that actually formed. The badge grades it.
 */
export function BandProjectionChart({
  title,
  symbol,
  bars,
  scenario,
  flow,
}: {
  title: string;
  /** Stable key for the frozen forecast kept in localStorage. */
  symbol: string;
  bars: IntradayBar[];
  scenario?: BandScenario;
  flow?: OrderFlowSnapshot;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const theme = useTheme();
  const chartRef = useRef<IChartApi | null>(null);
  const candlesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const linesRef = useRef<ISeriesApi<"Line">[]>([]);
  const lastBarTimeRef = useRef<number | null>(null);
  // undefined = not read from storage yet.
  const historyRef = useRef<BandForecast[] | undefined>(undefined);
  const [score, setScore] = useState<ForecastScore | null>(null);
  const [routeScore, setRouteScore] = useState<RouteScore | null>(null);
  const scoreKeyRef = useRef<string>("");
  const historySigRef = useRef<string>("");

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
    const line = (color: string, style: LineStyle, width: 1 | 2 = 1) =>
      chart.addLineSeries({
        color,
        lineWidth: width,
        lineStyle: style,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    // Order matches the datasets pushed below.
    linesRef.current = [
      line(BAND, LineStyle.Solid),
      line(MID, LineStyle.Solid),
      line(BAND, LineStyle.Solid),
      line(BAND, LineStyle.Dashed),
      line(MID, LineStyle.Dashed),
      line(BAND, LineStyle.Dashed),
      line(ROUTE, LineStyle.Dashed, 2),
      line(PAST, LineStyle.Dashed, 2),
      line(PAST, LineStyle.Dotted),
      line(PAST, LineStyle.Dashed, 2),
      line(PAST_ROUTE, LineStyle.Solid, 2),
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

  // Push the polled bars + recompute bands / route
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

    const lastTime = candleData[candleData.length - 1].time as number;
    const lastClose = bars[bars.length - 1].close;
    const route = scenario?.path ?? [];
    const proj = computeBandProjection(
      bars.map((b) => ({ time: sec(b.timestamp), close: b.close })),
      {
        horizon: FALLBACK_HORIZON,
        futureCloses: route.length ? route.map((p) => p.median) : undefined,
      },
    );
    // The route starts at the last real bar so it continues the price instead
    // of floating detached from it.
    const stepTime = (step: number) => lastTime + step * 300;
    const routeLine = (pick: (p: BandScenario["path"][number]) => number) =>
      route.length
        ? [
            { time: lastTime, value: lastClose },
            ...route.map((p) => ({ time: stepTime(p.step), value: pick(p) })),
          ]
        : [];
    // One snapshot per bar; draw the one that has fully played out, so the
    // purple always shows a COMPLETE forecast against the candles that
    // followed and slides forward a bar at a time instead of blanking out.
    // Cold start (no snapshot old enough yet) → rebuild it from the trend.
    const closes = bars.map((b) => ({ time: sec(b.timestamp), close: b.close }));
    if (historyRef.current === undefined) historyRef.current = loadHistory(symbol);
    const history = updateHistory(
      historyRef.current,
      proj,
      closes,
      routeLine((p) => p.median),
    );
    historyRef.current = history;
    // Written once per bar, not on every 5s poll.
    const sig = `${history.length}:${history[history.length - 1]?.anchor ?? 0}`;
    if (sig !== historySigRef.current) {
      historySigRef.current = sig;
      saveHistory(symbol, history);
    }
    // Oldest first; the newest is the one the badge grades.
    const windows = gradedWindows(history, closes);
    const locked = windows[windows.length - 1] ?? null;
    // Only push it to state when it really changed — this effect runs on every
    // 5s poll and a fresh object would re-render the card for nothing.
    const next = locked ? scoreForecast(locked, proj, closes) : null;
    const nextRoute = locked ? scoreRoute(locked, closes) : null;
    const key = JSON.stringify([next, nextRoute]);
    if (key !== scoreKeyRef.current) {
      scoreKeyRef.current = key;
      setScore(next);
      setRouteScore(nextRoute);
    }
    // Every window in one series, split by a blank bar between them so the
    // segments read as separate forecasts instead of one wandering line.
    const barIndex = new Map(closes.map((c, i) => [c.time, i]));
    const pastLine = (pick: (f: BandForecast) => BandPoint[]) => {
      const out: (LineData | WhitespaceData)[] = [];
      for (const f of windows) {
        if (out.length > 0) {
          const i = barIndex.get(f.anchor);
          if (i != null && i > 0) out.push({ time: closes[i - 1].time as UTCTimestamp });
        }
        for (const p of pick(f)) {
          if (p.time <= lastTime) out.push({ time: p.time as UTCTimestamp, value: p.value });
        }
      }
      return out.length >= 2 ? out : [];
    };

    const datasets: (LineData | WhitespaceData)[][] = [
      toLineData(proj.upper),
      toLineData(proj.mid),
      toLineData(proj.lower),
      toLineData(proj.projUpper),
      toLineData(proj.projMid),
      toLineData(proj.projLower),
      toLineData(routeLine((p) => p.median)),
      pastLine((f) => f.upper),
      pastLine((f) => f.mid),
      pastLine((f) => f.lower),
      pastLine((f) => f.route ?? []),
    ];
    linesRef.current.forEach((s, i) => s.setData(datasets[i]));

    // Frame the last hours + the projection — but only when a NEW bar lands,
    // so the 5s forming-bar refresh doesn't fight the user's own zoom/scroll.
    if (lastBarTimeRef.current !== lastTime) {
      lastBarTimeRef.current = lastTime;
      const ahead = route.length || FALLBACK_HORIZON;
      chartRef.current?.timeScale().setVisibleLogicalRange({
        from: candleData.length - VISIBLE_BARS,
        to: candleData.length + ahead + 1,
      });
    }
  }, [bars, scenario, symbol]);

  const last = bars.length > 0 ? bars[bars.length - 1].close : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{title}</CardTitle>
            <BandOddsBadges scenario={scenario} closes={bars.map((b) => b.close)} />
            {score && <ForecastScoreBadge score={score} />}
            {routeScore && <RouteScoreBadge score={routeScore} />}
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

/** How the frozen (purple) forecast held up against the bands that actually
 * formed. The error is the typical gap between the two, measured in band
 * widths, so it means the same thing on GOLD and on US30: 10% = the forecast
 * line sat a tenth of a band width away from the real one. Green = it worked
 * out, amber = loose, red = it missed (or the middle band went the other way).
 */
function ForecastScoreBadge({ score }: { score: ForecastScore }) {
  const err = Math.round(score.errPct * 100);
  const tone =
    !score.dirOk || score.errPct > 0.35
      ? "bg-red-500/15 text-red-400"
      : score.errPct > 0.15
        ? "bg-amber-500/15 text-amber-400"
        : "bg-emerald-500/15 text-emerald-400";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums ${tone}`}
      title={
        `previsão roxa mais recente (feita ${score.total} candles atrás, ${score.bars} já julgados) ` +
        `contra as bandas que se formaram: erro típico de ${err}% da largura da banda · ` +
        `direção da média ${score.dirOk ? "certa" : "errada"} · ` +
        `${score.outside} de ${score.bars} candles fecharam fora da previsão` +
        (score.drift
          ? " · esta foi reconstruída pela tendência do momento (a medida entra quando ela expirar)"
          : "")
      }
    >
      <Crosshair className="size-3.5" />
      {`±${err}%`}
    </span>
  );
}

/** Did the frozen price route (fuchsia) point the right way. The route is the
 * TYPICAL path of past analogs, so the side it pointed to is the real claim —
 * that is what the tick/cross says. How far the closes ran from it lives in the
 * tooltip, in band widths. */
function RouteScoreBadge({ score }: { score: RouteScore }) {
  const err = Math.round(score.errPct * 100);
  const tone = score.dirOk
    ? "bg-emerald-500/15 text-emerald-400"
    : "bg-red-500/15 text-red-400";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold ${tone}`}
      title={
        `caminho do preço previsto ${score.total} candles atrás (linha rosa no gráfico): ` +
        `o preço foi pro lado ${score.dirOk ? "previsto" : "contrário"} · ` +
        `distância típica do caminho: ${err}% da largura da banda ` +
        `(${score.bars} de ${score.total} candles julgados)`
      }
    >
      <Route className="size-3.5" />
      {score.dirOk ? "caminho ✓" : "caminho ✗"}
    </span>
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
