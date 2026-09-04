"use client";

import { useCallback, useSyncExternalStore } from "react";
import type { AssetSymbol } from "@/lib/types";

/**
 * Per-asset cap on how many lots may be open at once. It is a visual alert
 * only: nothing blocks or closes orders, the dashboard just lights up the
 * symbol when the open volume reaches (or passes) the cap.
 *
 * Defaults match the ActivTrades account (about $1k), traded with 0.01 lots:
 * 0.15 on every symbol, so the alert lights up after about 15 entries of the
 * minimum size are open at once. They are stored in the browser (localStorage),
 * so each device keeps its own copy and editing them needs no backend
 * round-trip.
 */
export const DEFAULT_LOT_LIMITS: Record<string, number> = {
  USTEC: 0.15,
  SPX: 0.15,
  GOLD: 0.15,
  US30: 0.15,
  GER40: 0.15,
  EURUSD: 0.15,
};

const STORAGE_KEY = "orderflow.lotLimits";

/** Sum of the open volume of every position on one symbol. */
export function openLots(positions: { volume: number }[] | undefined): number {
  return (positions ?? []).reduce((sum, p) => sum + p.volume, 0);
}

function readSaved(): Record<string, number> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const out: Record<string, number> = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === "number" && Number.isFinite(value) && value > 0) out[key] = value;
    }
    return out;
  } catch {
    // Corrupt/blocked storage: fall back to the defaults instead of crashing.
    return {};
  }
}

/**
 * Tiny store around localStorage so React can read it without a setState in an
 * effect (which would double-render every mount). The server snapshot is the
 * plain defaults, so the first client render matches the HTML and the saved
 * values arrive right after hydration.
 */
let cache: Record<string, number> | null = null;
const listeners = new Set<() => void>();

function getSnapshot(): Record<string, number> {
  if (cache === null) cache = { ...DEFAULT_LOT_LIMITS, ...readSaved() };
  return cache;
}

function getServerSnapshot(): Record<string, number> {
  return DEFAULT_LOT_LIMITS;
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function publish(next: Record<string, number> | null) {
  cache = next;
  for (const listener of listeners) listener();
}

/** The current limits plus the two editing actions used by the config panel. */
export function useLotLimits() {
  const limits = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const setLimit = useCallback((symbol: AssetSymbol, lots: number) => {
    const next = { ...getSnapshot(), [symbol]: lots };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    publish(next);
  }, []);

  const resetLimits = useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY);
    publish({ ...DEFAULT_LOT_LIMITS });
  }, []);

  return { limits, setLimit, resetLimits };
}
