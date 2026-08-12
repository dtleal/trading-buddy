/**
 * Bollinger Bands (standard 20-period SMA ± 2σ on closes) plus a projected
 * continuation of the three lines for the next few bars.
 *
 * The projection is an EXTRAPOLATION, not a forecast: future closes are
 * assumed to follow the drift of the last `period` closes (least-squares
 * slope), and the bands are recomputed over the extended series. Because the
 * rolling window still holds mostly real closes over a short horizon, the
 * width stays honest for the first handful of projected bars.
 */

export interface BandPoint {
  time: number; // unix seconds
  value: number;
}

export interface BandProjection {
  upper: BandPoint[];
  mid: BandPoint[];
  lower: BandPoint[];
  /** Dashed continuations. Each starts at the last real point so the line
   * visually continues instead of floating. */
  projUpper: BandPoint[];
  projMid: BandPoint[];
  projLower: BandPoint[];
  /** The assumed future close path (the drift line the projection rides). */
  projClose: BandPoint[];
}

const EMPTY: BandProjection = {
  upper: [],
  mid: [],
  lower: [],
  projUpper: [],
  projMid: [],
  projLower: [],
  projClose: [],
};

function mean(xs: number[]): number {
  return xs.reduce((a, b) => a + b, 0) / xs.length;
}

function stdev(xs: number[], mu: number): number {
  return Math.sqrt(xs.reduce((a, x) => a + (x - mu) ** 2, 0) / xs.length);
}

/** Least-squares slope of the closes (price change per bar). */
function slope(xs: number[]): number {
  const n = xs.length;
  const xMean = (n - 1) / 2;
  const yMean = mean(xs);
  let num = 0;
  let den = 0;
  for (let i = 0; i < n; i++) {
    num += (i - xMean) * (xs[i] - yMean);
    den += (i - xMean) ** 2;
  }
  return den === 0 ? 0 : num / den;
}

export interface BandOdds {
  /** Chance (0–1) that the upper band is touched before the lower one. */
  pUp: number;
  /** Set when the last close is already at/through a band — then there is no
   * probability to report, price is THERE. The UI says so instead of "100%". */
  at: "upper" | "lower" | null;
}

/**
 * Odds that price touches the UPPER band before the lower one.
 *
 * Same assumptions as the projection: price is a random walk with the recent
 * drift (least-squares slope of the last `period` closes) and the volatility
 * of the last `period` close-to-close changes. For that process the chance of
 * hitting a barrier A above before B below has a closed form (first-passage
 * of Brownian motion with drift); with zero drift it reduces to B/(A+B) —
 * "whichever band is closer is likelier". Bands are treated as static
 * barriers, fine for a ~30 min horizon. Returns null without enough bars.
 */
export function bandTouchOdds(
  closes: number[],
  { period = 20, mult = 2 } = {},
): BandOdds | null {
  const n = closes.length;
  if (n < period + 1) return null;

  const window = closes.slice(n - period);
  const mu = mean(window);
  const sd = stdev(window, mu);
  const upper = mu + mult * sd;
  const lower = mu - mult * sd;
  const last = closes[n - 1];
  const a = upper - last; // distance up
  const b = last - lower; // distance down
  if (a <= 0) return { pUp: 1, at: "upper" };
  if (b <= 0) return { pUp: 0, at: "lower" };

  const drift = slope(window);
  const diffs = window.slice(1).map((c, i) => c - window[i]);
  const dMean = mean(diffs);
  const vol = stdev(diffs, dMean);
  const k = vol === 0 ? 0 : (2 * drift) / (vol * vol);
  // No usable drift → the distance-only form.
  if (Math.abs(k) < 1e-12) return { pUp: b / (a + b), at: null };
  // exp args clamped: beyond ±50 the ratio is saturated at 0/1 anyway.
  const clamp = (x: number) => Math.max(-50, Math.min(50, x));
  const eB = Math.exp(clamp(k * b));
  const eA = Math.exp(clamp(-k * a));
  return { pUp: (1 - eB) / (eA - eB), at: null };
}

export function computeBandProjection(
  bars: { time: number; close: number }[],
  { period = 20, mult = 2, horizon = 6, stepSec = 300 } = {},
): BandProjection {
  const n = bars.length;
  if (n < period) return EMPTY;

  const closes = bars.map((b) => b.close);
  const upper: BandPoint[] = [];
  const mid: BandPoint[] = [];
  const lower: BandPoint[] = [];
  const bandAt = (series: number[], k: number): [number, number, number] => {
    const window = series.slice(k - period + 1, k + 1);
    const mu = mean(window);
    const sd = stdev(window, mu);
    return [mu + mult * sd, mu, mu - mult * sd];
  };
  for (let k = period - 1; k < n; k++) {
    const [u, m, l] = bandAt(closes, k);
    const time = bars[k].time;
    upper.push({ time, value: u });
    mid.push({ time, value: m });
    lower.push({ time, value: l });
  }

  // Future closes ride the recent drift; bands are recomputed over the
  // extended series so the SMA keeps sliding instead of freezing.
  const drift = slope(closes.slice(n - period));
  const lastTime = bars[n - 1].time;
  const lastClose = closes[n - 1];
  const extended = closes.slice();
  const projUpper: BandPoint[] = [upper[upper.length - 1]];
  const projMid: BandPoint[] = [mid[mid.length - 1]];
  const projLower: BandPoint[] = [lower[lower.length - 1]];
  const projClose: BandPoint[] = [{ time: lastTime, value: lastClose }];
  for (let i = 1; i <= horizon; i++) {
    extended.push(lastClose + drift * i);
    const [u, m, l] = bandAt(extended, extended.length - 1);
    const time = lastTime + stepSec * i;
    projUpper.push({ time, value: u });
    projMid.push({ time, value: m });
    projLower.push({ time, value: l });
    projClose.push({ time, value: extended[extended.length - 1] });
  }

  return { upper, mid, lower, projUpper, projMid, projLower, projClose };
}
