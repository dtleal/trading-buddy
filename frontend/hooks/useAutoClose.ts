"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AutoCloseStatus } from "@/lib/types";

/**
 * Polls the auto-close status and exposes the arm/disarm/close actions.
 *
 * Status is polled (not streamed) every `POLL_MS` — it changes rarely and a
 * 1.5s lag on the ARMED indicator is fine; the real-time feedback that a close
 * happened is the positions vanishing from the live flow. The mutating actions
 * return the fresh status (or throw an ApiError the caller can surface).
 */
const POLL_MS = 1500;

export function useAutoClose(): {
  status: AutoCloseStatus | null;
  arm: (targetUsd: number) => Promise<void>;
  disarm: () => Promise<void>;
  closeSymbol: (symbol: string) => Promise<void>;
} {
  const [status, setStatus] = useState<AutoCloseStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.getAutoClose());
    } catch {
      /* transient; next poll retries */
    }
  }, []);

  useEffect(() => {
    // Defer the initial fetch out of the effect body (a timer callback, not a
    // synchronous setState-in-effect), then poll on the interval.
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  const arm = useCallback(async (targetUsd: number) => {
    setStatus(await api.setAutoClose(true, targetUsd));
  }, []);

  const disarm = useCallback(async () => {
    setStatus(await api.setAutoClose(false, null));
  }, []);

  const closeSymbol = useCallback(
    async (symbol: string) => {
      await api.closeSymbol(symbol);
      await refresh();
    },
    [refresh],
  );

  return { status, arm, disarm, closeSymbol };
}
