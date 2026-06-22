"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BotStatus } from "@/lib/types";

/** Polls the scalper-bot status and exposes arm/disarm. Same cadence/rationale
 *  as useAutoClose — status changes rarely; the live feedback is positions
 *  appearing/closing in the flow. */
const POLL_MS = 1500;

export function useScalperBot(): {
  status: BotStatus | null;
  arm: (profitTarget: number, lossStop: number) => Promise<void>;
  disarm: () => Promise<void>;
} {
  const [status, setStatus] = useState<BotStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.getBot());
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

  const arm = useCallback(async (profitTarget: number, lossStop: number) => {
    setStatus(await api.setBot(true, profitTarget, lossStop));
  }, []);

  const disarm = useCallback(async () => {
    setStatus(await api.setBot(false, null, null));
  }, []);

  return { status, arm, disarm };
}
