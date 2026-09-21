"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { IbovResponse } from "@/lib/types";

/**
 * Polls the top-of-the-index panel. The quote behind it is delayed ~15 min, so
 * a faster poll would only redraw the same number.
 */
const POLL_MS = 60_000;

export function useIbov(): IbovResponse | null {
  const [data, setData] = useState<IbovResponse | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.getIbov());
    } catch {
      /* a strip that fails stays on the last number instead of blanking */
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

  return data;
}
