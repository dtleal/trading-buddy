"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BandScenariosBySymbol, CandlesBySymbol } from "@/lib/types";

/**
 * Polls the per-symbol M5 candle history. The collector pushes it every ~5s,
 * so a 5s poll keeps the forming bar (and the projection) close to live.
 */
const POLL_MS = 5_000;

/** The scenario is read off the bar still forming, so it moves with every tick,
 * not only when a 5m bar closes — polling it slower than the candles left the
 * badges showing a stale read while the chart had already crossed the middle
 * band. Same 5s as the candles: the analog search costs ~150ms for all symbols. */
const SCENARIO_POLL_MS = POLL_MS;

export function useCandles(): CandlesBySymbol | null {
  const [candles, setCandles] = useState<CandlesBySymbol | null>(null);

  const refresh = useCallback(async () => {
    try {
      setCandles(await api.getCandles());
    } catch {
      /* transient; next poll retries */
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  return candles;
}

export function useBandScenarios(): BandScenariosBySymbol | null {
  const [scenarios, setScenarios] = useState<BandScenariosBySymbol | null>(null);

  const refresh = useCallback(async () => {
    try {
      setScenarios(await api.getBandScenarios());
    } catch {
      /* transient; next poll retries */
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, SCENARIO_POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  return scenarios;
}
