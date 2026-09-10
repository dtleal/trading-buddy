"use client";

import { useEffect, useRef, useState } from "react";
import { OrderFlowClient, type ConnectionStatus } from "@/lib/orderflowWs";
import type { AssetSymbol, OrderFlowSnapshot } from "@/lib/types";

/**
 * Subscribes to /ws/orderflow and keeps the latest snapshot per symbol.
 * Returns a map keyed by AssetSymbol plus the connection status. Single
 * shared client per page; survives strict-mode double-invoke.
 *
 * `receivedAt` is when each snapshot LANDED in the browser, on the
 * `performance.now()` clock (monotonic — it never jumps). Freshness must be
 * measured with it, never by comparing the snapshot's `asof` to `Date.now()`:
 * `asof` comes from the broker/collector clock and `Date.now()` from the
 * browser machine, so a machine whose clock is off by a minute reads live data
 * as stale (and flips between "ao vivo" and "sem dados" as the clock is pulled
 * back and forth by NTP).
 */
export function useOrderFlow(): {
  flows: Partial<Record<AssetSymbol, OrderFlowSnapshot>>;
  receivedAt: Partial<Record<AssetSymbol, number>>;
  status: ConnectionStatus;
} {
  const [flows, setFlows] = useState<Partial<Record<AssetSymbol, OrderFlowSnapshot>>>({});
  const [receivedAt, setReceivedAt] = useState<Partial<Record<AssetSymbol, number>>>({});
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const clientRef = useRef<OrderFlowClient | null>(null);

  useEffect(() => {
    const client = new OrderFlowClient();
    clientRef.current = client;
    const offSnap = client.onSnapshot((snap) => {
      setFlows((prev) => ({ ...prev, [snap.symbol]: snap }));
      setReceivedAt((prev) => ({ ...prev, [snap.symbol]: performance.now() }));
    });
    const offStatus = client.onStatus(setStatus);
    client.start();
    return () => {
      offSnap();
      offStatus();
      client.stop();
    };
  }, []);

  return { flows, receivedAt, status };
}
