"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AutoBreakevenStatus } from "@/lib/types";

/**
 * Polls the per-position auto-breakeven status and exposes arm/disarm.
 *
 * Same cadence and reasoning as `useAutoClose`: the state changes rarely, and
 * the real-time feedback that a stop moved is the position's SL showing up at
 * the entry price in the live flow.
 */
const POLL_MS = 1500;

export function useAutoBreakeven(): {
  status: AutoBreakevenStatus | null;
  arm: (thresholdUsd: number) => Promise<void>;
  disarm: () => Promise<void>;
} {
  const [status, setStatus] = useState<AutoBreakevenStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.getAutoBreakeven());
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

  const arm = useCallback(async (thresholdUsd: number) => {
    setStatus(await api.setAutoBreakeven(true, thresholdUsd));
  }, []);

  const disarm = useCallback(async () => {
    setStatus(await api.setAutoBreakeven(false, null));
  }, []);

  return { status, arm, disarm };
}
