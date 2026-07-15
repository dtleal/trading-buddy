"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AccountPnl } from "@/lib/types";

/**
 * Polls realized account P&L (calendar day/week/month). The collector recomputes
 * it every ~30s (it only moves when a trade closes), so a 15s poll here keeps
 * the top-of-screen cards fresh without hammering the backend.
 */
const POLL_MS = 15_000;

export function usePnl(): AccountPnl | null {
  const [pnl, setPnl] = useState<AccountPnl | null>(null);

  const refresh = useCallback(async () => {
    try {
      setPnl(await api.getAccountPnl());
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

  return pnl;
}
