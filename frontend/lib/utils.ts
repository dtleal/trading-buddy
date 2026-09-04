/**
 * Conditional className merger.
 * Combines `clsx` (for conditional class strings) with `tailwind-merge`
 * (to resolve conflicting Tailwind utilities like `px-4 px-6`).
 */
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** How many decimals a price needs to still say something.
 *
 * The indices read fine with two (30,075.68), but EURUSD trades at 1.15957 —
 * two decimals there would hide a whole day of movement, so anything priced
 * under 10 gets five. Mirrors `price_digits` in the backend.
 *
 * Pass the *price* even when formatting something derived from it (a spread, a
 * gap to a level): a 1.45-point spread on the Nasdaq should still read 1.45,
 * not 1.45000.
 */
export function priceDigits(price: number | null | undefined): number {
  if (price === null || price === undefined || Number.isNaN(price)) return 2;
  return Math.abs(price) < 10 ? 5 : 2;
}

/** Format a numeric price for display. Digit count follows the price size
 *  unless `digits` says otherwise. */
export function fmtPrice(v: number | null | undefined, digits?: number): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const d = digits ?? priceDigits(v);
  return v.toLocaleString("en-US", {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
}

/** Format a percentage value with sign. */
export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}
