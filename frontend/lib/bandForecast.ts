/**
 * Keeps past band projections around so they can be graded on the chart.
 *
 * The Bandas chart draws the bands' continuation to the right of the last
 * candle. On its own that line is useless as a check: the next tick redraws it,
 * so you never see whether the previous one was right. So one snapshot is kept
 * per closed bar, and the chart draws the snapshots that have fully played out,
 * pinned to their own timestamps with the real candles sitting on top of them.
 * `GRADED_WINDOWS` of them are drawn back to back, so the last ~20 candles are
 * covered by forecasts instead of just the last 8. They slide forward one bar
 * at a time, so the comparison is always complete and never blanks out.
 */

import { computeBandProjection, type BandPoint, type BandProjection } from "./bollinger";

/** Bars a frozen forecast covers, i.e. how far back the graded one sits.
 * 8 bars = 40 min on M5: long enough to be a real forecast, short enough that
 * it stays right next to the price. */
export const FROZEN_BARS = 8;
/** How many frozen forecasts are drawn side by side. Each window covers
 * FROZEN_BARS + 1 bars and they are spaced one bar apart, so two of them reach
 * back ~20 candles — enough to see whether the projection has been reliable
 * lately, not just on the last window. */
export const GRADED_WINDOWS = 2;
/** Bars between the anchors of two drawn windows: the window itself plus one
 * empty bar, which is what breaks the purple line into separate segments. */
const WINDOW_STEP = FROZEN_BARS + 2;
/** Snapshots kept per symbol — every drawn window plus a little slack. */
const MAX_HISTORY = FROZEN_BARS + (GRADED_WINDOWS - 1) * WINDOW_STEP + 4;

/** A projection frozen at one bar. */
export interface BandForecast {
  /** Time of the last real bar when it was taken (unix seconds). */
  anchor: number;
  /** Frozen lines, starting at the anchor bar (index 0 is the real value). */
  upper: BandPoint[];
  mid: BandPoint[];
  lower: BandPoint[];
  /** The measured price route frozen with it (index 0 is the anchor close).
   * Missing on rebuilt snapshots and when the sample was too thin. */
  route?: BandPoint[];
  /** True when it was rebuilt from the recent trend (see `backfillForecast`)
   * instead of frozen live off the measured route. */
  drift?: boolean;
}

/** How the frozen forecast held up against the bands that actually formed. */
export interface ForecastScore {
  /** Closed bars graded so far. */
  bars: number;
  /** Bars the forecast covers in total. */
  total: number;
  /** Typical gap between forecast and real band, as a share of band width. */
  errPct: number;
  /** Did the middle band travel the way the forecast said it would. */
  dirOk: boolean;
  /** Graded bars that closed outside the forecast envelope. */
  outside: number;
  /** The forecast was rebuilt from the trend, not the measured route. */
  drift: boolean;
}

/** Freeze the live projection. Null when there is no projection to freeze. */
export function takeForecast(
  proj: BandProjection,
  route?: BandPoint[],
  steps = FROZEN_BARS,
): BandForecast | null {
  if (proj.projMid.length < 2) return null;
  const cut = <T,>(xs: T[]) => xs.slice(0, steps + 1);
  return {
    anchor: proj.projMid[0].time,
    upper: cut(proj.projUpper),
    mid: cut(proj.projMid),
    lower: cut(proj.projLower),
    ...(route && route.length >= 2 ? { route: cut(route) } : {}),
  };
}

/**
 * Rebuild the forecast the chart WOULD have drawn `back` bars ago, using only
 * the bars up to that point. Used on a cold start, before enough live snapshots
 * exist: it rides the recent trend instead of the measured route (that one is
 * only known for the current bar), so it is flagged `drift`.
 */
export function backfillForecast(
  bars: { time: number; close: number }[],
  back = FROZEN_BARS,
): BandForecast | null {
  if (bars.length <= back + 1) return null;
  const past = bars.slice(0, bars.length - back);
  const f = takeForecast(computeBandProjection(past, { horizon: FROZEN_BARS }));
  return f ? { ...f, drift: true } : null;
}

/** Add this bar's snapshot to the history, drop what fell off the chart. */
export function updateHistory(
  history: BandForecast[],
  proj: BandProjection,
  bars: { time: number }[],
  route?: BandPoint[],
): BandForecast[] {
  if (bars.length === 0) return history;
  const first = bars[0].time;
  const last = bars[bars.length - 1].time;
  const kept = history.filter((f) => f.anchor >= first && f.anchor <= last);
  const fresh = takeForecast(proj, route);
  if (fresh && !kept.some((f) => f.anchor === fresh.anchor)) kept.push(fresh);
  kept.sort((a, b) => a.anchor - b.anchor);
  return kept.slice(-MAX_HISTORY);
}

/**
 * The forecasts to draw, oldest first: the ones anchored 8, 18, … bars back,
 * every one of them already played out in full. A window with no snapshot yet
 * (cold start) is rebuilt from the trend so the chart is never empty.
 */
export function gradedWindows(
  history: BandForecast[],
  bars: { time: number; close: number }[],
): BandForecast[] {
  const out: BandForecast[] = [];
  for (let i = 0; i < GRADED_WINDOWS; i++) {
    const back = FROZEN_BARS + i * WINDOW_STEP;
    const idx = bars.length - 1 - back;
    if (idx < 0) break;
    const anchor = bars[idx].time;
    const f = history.find((h) => h.anchor === anchor) ?? backfillForecast(bars, back);
    if (f) out.push(f);
  }
  return out.reverse();
}

/**
 * Grade the frozen forecast against the real bands.
 *
 * `bars` must be the closes actually on the chart; the last one is still
 * forming, so it is left out of the grade. Null until at least one bar closed
 * after the anchor.
 */
export function scoreForecast(
  f: BandForecast,
  proj: BandProjection,
  bars: { time: number; close: number }[],
): ForecastScore | null {
  if (bars.length < 2) return null;
  const lastClosed = bars[bars.length - 2].time;
  const real = new Map<number, [number, number, number]>();
  for (let i = 0; i < proj.mid.length; i++) {
    real.set(proj.mid[i].time, [proj.upper[i].value, proj.mid[i].value, proj.lower[i].value]);
  }
  const closes = new Map(bars.map((b) => [b.time, b.close]));

  const errors: number[] = [];
  let outside = 0;
  let lastStep: { fMid: number; rMid: number } | null = null;
  for (let i = 1; i < f.mid.length; i++) {
    const time = f.mid[i].time;
    if (time > lastClosed) break;
    const r = real.get(time);
    if (!r) continue;
    const [ru, rm, rl] = r;
    const width = ru - rl;
    if (width <= 0) continue;
    const fu = f.upper[i].value;
    const fm = f.mid[i].value;
    const fl = f.lower[i].value;
    errors.push((Math.abs(fu - ru) + Math.abs(fm - rm) + Math.abs(fl - rl)) / 3 / width);
    const close = closes.get(time);
    if (close != null && (close > fu || close < fl)) outside++;
    lastStep = { fMid: fm, rMid: rm };
  }
  if (errors.length === 0 || !lastStep) return null;

  const anchorMid = f.mid[0].value;
  const forecastMove = lastStep.fMid - anchorMid;
  const realMove = lastStep.rMid - anchorMid;
  return {
    bars: errors.length,
    total: f.mid.length - 1,
    errPct: median(errors),
    dirOk: forecastMove === 0 || realMove === 0 ? true : forecastMove * realMove > 0,
    outside,
    drift: !!f.drift,
  };
}

/** How the frozen price route held up against the closes that followed. */
export interface RouteScore {
  bars: number;
  total: number;
  /** Typical distance between the route and the real close, in band widths. */
  errPct: number;
  /** Did price end up on the side the route pointed to. */
  dirOk: boolean;
}

/**
 * Grade the frozen price route. It is a TYPICAL path (the median of past
 * analogs), not a point forecast, so what matters is the side it pointed to and
 * how far the real closes ran from it — measured in band widths so it means the
 * same thing on GOLD and on US30.
 */
export function scoreRoute(
  f: BandForecast,
  bars: { time: number; close: number }[],
): RouteScore | null {
  if (!f.route || f.route.length < 2 || bars.length < 2) return null;
  const width = f.upper[0].value - f.lower[0].value;
  if (width <= 0) return null;
  const lastClosed = bars[bars.length - 2].time;
  const closes = new Map(bars.map((b) => [b.time, b.close]));

  const errors: number[] = [];
  let lastStep: { pred: number; real: number } | null = null;
  for (let i = 1; i < f.route.length; i++) {
    const time = f.route[i].time;
    if (time > lastClosed) break;
    const close = closes.get(time);
    if (close == null) continue;
    errors.push(Math.abs(f.route[i].value - close) / width);
    lastStep = { pred: f.route[i].value, real: close };
  }
  if (errors.length === 0 || !lastStep) return null;

  const anchor = f.route[0].value;
  const predMove = lastStep.pred - anchor;
  const realMove = lastStep.real - anchor;
  return {
    bars: errors.length,
    total: f.route.length - 1,
    errPct: median(errors),
    dirOk: predMove === 0 || realMove === 0 ? true : predMove * realMove > 0,
  };
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

const KEY = "bandForecast.v4.";

/** The history outlives a reload — it takes 40 min to build one grade. */
export function loadHistory(symbol: string): BandForecast[] {
  try {
    const raw = localStorage.getItem(KEY + symbol);
    const list = raw ? (JSON.parse(raw) as BandForecast[]) : [];
    return Array.isArray(list) ? list.filter((f) => f?.mid?.length >= 2) : [];
  } catch {
    return [];
  }
}

export function saveHistory(symbol: string, history: BandForecast[]): void {
  try {
    localStorage.setItem(KEY + symbol, JSON.stringify(history));
  } catch {
    /* private mode / quota — the history just won't survive a reload */
  }
}
