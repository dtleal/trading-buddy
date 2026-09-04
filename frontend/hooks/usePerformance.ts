"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PerformanceQuery, PerformanceReport } from "@/lib/types";

/**
 * Polls the performance report for the current filter selection. The collector
 * re-reads the broker's deal history every ~5 min, so a 30s poll is plenty —
 * it also picks up a trade closed by hand a few seconds after the push.
 *
 * Changing a filter keeps the previous report on screen until the new one
 * lands (a fetch takes milliseconds), so the page doesn't flash empty.
 */
const POLL_MS = 30_000;

export function usePerformance(query: PerformanceQuery): {
  report: PerformanceReport | null;
  loading: boolean;
  error: string | null;
} {
  const [report, setReport] = useState<PerformanceReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // The query object is rebuilt on every render, so key the effect by its
  // serialized form instead — otherwise every render restarts the poll.
  const key = JSON.stringify(query);

  const refresh = useCallback(async () => {
    try {
      setReport(await api.getPerformance(JSON.parse(key) as PerformanceQuery));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  return { report, loading, error };
}
