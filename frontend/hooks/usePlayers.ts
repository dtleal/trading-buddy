"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PlayersResponse } from "@/lib/types";

/**
 * Polls the Baleia/Banco/Sardinha read. The collector pushes prints as they
 * happen, so what is on screen is only ever as fresh as this poll — at 3s the
 * price visibly lagged the Profit window. The backend answer is a snapshot it
 * already holds in memory (no file parsing per request), so 1s costs almost
 * nothing.
 */
const POLL_MS = 1_000;

export function usePlayers(
  get: () => Promise<PlayersResponse> = api.getPlayers,
): { data: PlayersResponse | null; error: boolean } {
  const [data, setData] = useState<PlayersResponse | null>(null);
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setData(await get());
      setError(false);
    } catch {
      setError(true);
    }
  }, [get]);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  return { data, error };
}
