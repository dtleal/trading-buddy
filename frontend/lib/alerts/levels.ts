/**
 * Proximity of the live price to the previous day's high / low (PDH / PDL).
 *
 * The user wants a loud heads-up when the 5m is *approaching* yesterday's
 * extreme — that's where the market tends to react (rejection or breakout).
 *
 * PDH/PDL come from the 5m dashboard tick (`intraday_levels`); the live price
 * comes from the real-time order-flow book (freshest), falling back to the
 * tick's `last_price`. Distance is scaled by ATR so one threshold works across
 * USTEC (~20k), USA500 (~6k) and GOLD (~3k).
 */
import type { AssetSymbol, IntradayLevels, OrderFlowSnapshot } from "@/lib/types";

/** Within this many ATRs of the level → "approaching" (loud amber). */
export const NEAR_ATR = 0.3;
/** Within this many ATRs (or already broken) → "at the level" (loud red). */
export const AT_ATR = 0.08;

export type ProximityTier = "none" | "near" | "at";
export type LevelKind = "PDH" | "PDL";

export interface LevelProximity {
  symbol: AssetSymbol;
  label: string;
  kind: LevelKind;
  /** The yesterday extreme being approached. */
  target: number;
  /** Live price used for the comparison. */
  price: number;
  /** Signed points to the level (>0 still shy of it, <=0 broken through). */
  gap: number;
  /** |gap| expressed in ATRs — the tier driver. */
  atrGap: number;
  tier: ProximityTier;
  /** True once the price has traded through the level. */
  broken: boolean;
}

/** Best live price for a symbol: book mid → last tape print → tick last_price. */
export function livePrice(
  flow: OrderFlowSnapshot | undefined,
  levels: IntradayLevels | undefined,
): number | null {
  const bid = flow?.book?.bids?.[0]?.price ?? null;
  const ask = flow?.book?.asks?.[0]?.price ?? null;
  if (bid != null && ask != null) return (bid + ask) / 2;
  const lastTrade = flow?.recent_trades?.at(-1)?.price ?? null;
  if (lastTrade != null) return lastTrade;
  return levels?.last_price ?? null;
}

function tierFor(atrGap: number): ProximityTier {
  if (atrGap <= AT_ATR) return "at";
  if (atrGap <= NEAR_ATR) return "near";
  return "none";
}

/**
 * The most relevant level for one symbol — whichever of PDH/PDL the price is
 * closest to (by ATR). Returns null if we lack the inputs or nothing is close.
 */
export function computeProximity(
  symbol: AssetSymbol,
  label: string,
  levels: IntradayLevels | undefined,
  price: number | null,
): LevelProximity | null {
  if (!levels || price == null) return null;
  // ATR scales the threshold; fall back to 0.1% of price if it's missing.
  const scale = levels.atr_14 && levels.atr_14 > 0 ? levels.atr_14 : Math.abs(price) * 0.001;
  if (scale <= 0) return null;

  const candidates: LevelProximity[] = [];
  const push = (kind: LevelKind, target: number | null, gap: number) => {
    if (target == null) return;
    candidates.push({
      symbol,
      label,
      kind,
      target,
      price,
      gap,
      atrGap: Math.abs(gap) / scale,
      tier: tierFor(Math.abs(gap) / scale),
      broken: gap <= 0,
    });
  };
  // gap > 0 means the price hasn't reached the level yet.
  push("PDH", levels.pdh, levels.pdh != null ? levels.pdh - price : 0);
  push("PDL", levels.pdl, levels.pdl != null ? price - levels.pdl : 0);

  const relevant = candidates.filter((c) => c.tier !== "none");
  if (relevant.length === 0) return null;
  // Nearest wins (smallest ATR gap).
  return relevant.sort((a, b) => a.atrGap - b.atrGap)[0];
}
