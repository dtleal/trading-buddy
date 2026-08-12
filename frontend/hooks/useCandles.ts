"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CandlesBySymbol } from "@/lib/types";

/**
 * Polls the per-symbol M5 candle history. The collector pushes it every ~5s,
 * so a 5s poll keeps the forming bar (and the projection) close to live.
 */
const POLL_MS = 5_000;

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
