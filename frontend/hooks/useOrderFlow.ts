"use client";

import { useEffect, useRef, useState } from "react";
import { OrderFlowClient, type ConnectionStatus } from "@/lib/orderflowWs";
import type { AssetSymbol, OrderFlowSnapshot } from "@/lib/types";

/**
 * Subscribes to /ws/orderflow and keeps the latest snapshot per symbol.
 * Returns a map keyed by AssetSymbol plus the connection status. Single
 * shared client per page; survives strict-mode double-invoke.
 */
export function useOrderFlow(): {
  flows: Partial<Record<AssetSymbol, OrderFlowSnapshot>>;
  status: ConnectionStatus;
} {
  const [flows, setFlows] = useState<Partial<Record<AssetSymbol, OrderFlowSnapshot>>>({});
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const clientRef = useRef<OrderFlowClient | null>(null);

  useEffect(() => {
    const client = new OrderFlowClient();
    clientRef.current = client;
    const offSnap = client.onSnapshot((snap) =>
      setFlows((prev) => ({ ...prev, [snap.symbol]: snap })),
    );
    const offStatus = client.onStatus(setStatus);
    client.start();
    return () => {
      offSnap();
      offStatus();
      client.stop();
    };
  }, []);

  return { flows, status };
}
