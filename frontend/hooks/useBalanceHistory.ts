"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AccountBalanceHistory } from "@/lib/types";

/**
 * Polls the account balance/equity series. The collector samples it every ~30s
 * (same read as realized P&L), so a 15s poll keeps the chart fresh without
 * hammering the backend — matches `usePnl`.
 */
const POLL_MS = 15_000;

export function useBalanceHistory(): AccountBalanceHistory | null {
  const [history, setHistory] = useState<AccountBalanceHistory | null>(null);

  const refresh = useCallback(async () => {
    try {
      setHistory(await api.getBalanceHistory());
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

  return history;
}
