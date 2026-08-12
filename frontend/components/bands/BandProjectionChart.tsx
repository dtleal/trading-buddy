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
import { ArrowDown, ArrowUp, Undo2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  bandTouchOdds,
  computeBandProjection,
  type BandOdds,
  type BandPoint,
} from "@/lib/bollinger";
import { PressureGauge } from "@/components/orderflow/PressureGauge";
import type { BandRegime, BandScenario, IntradayBar, OrderFlowSnapshot } from "@/lib/types";

const UP = "#10b981"; // emerald — up candles
const DOWN = "#ef4444"; // red — down candles
const BAND = "#60a5fa"; // blue-400 — upper/lower band
const MID = "#f59e0b"; // amber-500 — SMA20
const ROUTE = "#38bdf8"; // sky-400 — the measured route ahead
const CONE = "#0369a1"; // sky-800 — middle half of past outcomes

/** Bars ahead when there is no measured route to follow (6 × 5min = 30 min). */
const FALLBACK_HORIZON = 6;
/** Real bars kept in view (the rest stay scrollable to the left). Sized for a
 * three-across card: ~5h of context without squeezing the candles. */
const VISIBLE_BARS = 60;

/**
 * One symbol's 5m candles with standard Bollinger (20, 2), the route price
 * usually took from here, and the bands' continuation under that same route.
 *
 * The route (sky, dashed) and its cone (faint, the middle half of outcomes)
 * come from the backend: every past bar where price sat at this same spot
 * inside the band, and what happened over the next hour. No measured route
 * (thin sample / cold start) → the bands fall back to a drift extrapolation
 * and no route is drawn.
 */
export function BandProjectionChart({
  title,
  bars,
  scenario,
  flow,
}: {
  title: string;
  bars: IntradayBar[];
  scenario?: BandScenario;
  flow?: OrderFlowSnapshot;
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
      line(CONE, LineStyle.Dotted),
      line(CONE, LineStyle.Dotted),
      line(ROUTE, LineStyle.Dashed, 2),
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
    // Route + cone start at the last real bar so they continue the price
    // instead of floating detached from it.
    const stepTime = (step: number) => lastTime + step * 300;
    const routeLine = (pick: (p: BandScenario["path"][number]) => number) =>
      route.length
        ? [
            { time: lastTime, value: lastClose },
            ...route.map((p) => ({ time: stepTime(p.step), value: pick(p) })),
          ]
        : [];
    const datasets = [
      proj.upper,
      proj.mid,
      proj.lower,
      proj.projUpper,
      proj.projMid,
      proj.projLower,
      routeLine((p) => p.p75),
      routeLine((p) => p.p25),
      routeLine((p) => p.median),
    ];
    linesRef.current.forEach((s, i) => s.setData(toLineData(datasets[i])));

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
  }, [bars, scenario]);

  const last = bars.length > 0 ? bars[bars.length - 1].close : null;
  const odds = scenario
    ? scenarioOdds(scenario)
    : bandTouchOdds(bars.map((b) => b.close));
  // "Does it come back to the middle?" is only a real question at a band.
  const atBand =
    !!scenario && (scenario.pct_b <= AT_BAND || scenario.pct_b >= 1 - AT_BAND);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <CardTitle>{title}</CardTitle>
            {odds && <TouchOddsBadge odds={odds} measured={!!scenario} />}
            {scenario && atBand && <ReturnToMidBadge scenario={scenario} />}
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
        <div className="relative w-full" style={{ height: 320 }}>
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

/** Price is close enough to a band for "does it come back to the middle?" to
 * be a real question. In the middle of the band it is not — price is already
 * there, so the figure would be trivially high and mean nothing. */
const AT_BAND = 0.2;

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

/** Below this many analogs the figure is dimmed: still shown, but visibly
 * weaker, so a number built on a handful of cases never looks solid. */
const THIN_SAMPLE = 25;

/** "Volta pra média": of the past visits to THIS band in THIS market state,
 * how many got back to the middle within the hour. Only shown when price is
 * actually at a band — mid-band it would be trivially high and mean nothing.
 * Sky = usually comes back, amber = usually keeps going (a break, not a
 * bounce), grey = coin flip. Every detail lives in the tooltip. */
function ReturnToMidBadge({ scenario }: { scenario: BandScenario }) {
  const r = scenario.return_to_mid;
  if (!r) return null;
  const p = Math.round(r.pct * 100);
  const tone =
    p >= 60
      ? "bg-sky-500/15 text-sky-400"
      : p <= 40
        ? "bg-amber-500/15 text-amber-400"
        : "bg-zinc-800 text-zinc-300";
  const side = scenario.pct_b < 0.5 ? "de baixo" : "de cima";
  const held =
    r.matched_on.length > 0
      ? `no mesmo estado de mercado (${r.matched_on.join(" + ")})`
      : "sem conseguir filtrar o estado de mercado";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums ${tone} ${
        r.regime_n < THIN_SAMPLE ? "opacity-60" : ""
      }`}
      title={
        `das ${r.regime_n} vezes que o preço esteve na banda ${side} ${held}, ` +
        `${p}% voltaram pra média em até 1h` +
        (r.median_bars != null ? ` (tipicamente ~${r.median_bars} candles)` : "") +
        ` · sem olhar o estado: ${pct(scenario.back_to_mid_pct)}` +
        (r.regime_n < THIN_SAMPLE ? " · amostra pequena, leia com reserva" : "")
      }
    >
      <Undo2 className="size-3.5" />
      {p}% média
    </span>
  );
}

/** Which band gets touched first, and how likely. `measured` = the share comes
 * from the symbol's own history; otherwise it is the random-walk estimate used
 * until enough history is stored. Grey = coin flip (≤55%). Price already at or
 * past a band shows "na banda" — that is where it IS, not a probability. */
function TouchOddsBadge({ odds, measured }: { odds: BandOdds; measured: boolean }) {
  const up = odds.at ? odds.at === "upper" : odds.pUp >= 0.5;
  const p = Math.round((up ? odds.pUp : 1 - odds.pUp) * 100);
  const undecided = !odds.at && p <= 55;
  const tone = undecided
    ? "bg-zinc-800 text-zinc-300"
    : up
      ? "bg-emerald-500/15 text-emerald-400"
      : "bg-red-500/15 text-red-400";
  const Arrow = up ? ArrowUp : ArrowDown;
  const side = up ? "cima" : "baixo";
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs font-semibold tabular-nums ${tone}`}
      title={
        odds.at
          ? `preço já está na banda de ${side}`
          : measured
            ? `nas vezes anteriores que esteve aqui, ${p}% tocaram a banda de ${side} primeiro`
            : `${p}% de chance de tocar a banda de ${side} primeiro (estimativa por distância e volatilidade — ainda sem histórico suficiente para medir)`
      }
    >
      <Arrow className="size-3.5" />
      {odds.at ? "na banda" : `${p}%`}
    </span>
  );
}

/** The measured equivalent of `bandTouchOdds`: of the past visits here that
 * reached a band at all, the share that reached the upper one first. */
function scenarioOdds(s: BandScenario): BandOdds {
  const at = s.pct_b >= 1 ? "upper" : s.pct_b <= 0 ? "lower" : null;
  const up = s.upper_first?.n ?? 0;
  const down = s.lower_first?.n ?? 0;
  return { pUp: up + down > 0 ? up / (up + down) : 0.5, at };
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function sec(iso: string): number {
  return Math.floor(new Date(iso).getTime() / 1000);
}

function toLineData(points: BandPoint[]): LineData[] {
  return points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
}
