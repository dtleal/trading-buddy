"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PlayersResponse } from "@/lib/types";

/**
 * Polls the Baleia/Banco/Sardinha read. The backend only parses the bytes
 * Profit appended since the last call, so a 3s poll is cheap and keeps the
 * 15-minute window close to what the Profit screen shows.
 */
const POLL_MS = 3_000;

export function usePlayers(): { data: PlayersResponse | null; error: boolean } {
  const [data, setData] = useState<PlayersResponse | null>(null);
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setData(await api.getPlayers());
      setError(false);
    } catch {
      setError(true);
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

  return { data, error };
}
