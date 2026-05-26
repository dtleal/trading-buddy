"use client";

import { useEffect, useRef, useState } from "react";
import { TickClient, type ConnectionStatus } from "@/lib/ws";
import type { DashboardTick } from "@/lib/types";

/**
 * Subscribes to /ws/ticks and returns the latest tick + connection status.
 * Single shared client per page. Survives strict-mode double-invoke.
 */
export function useLiveTick(): {
  tick: DashboardTick | null;
  status: ConnectionStatus;
} {
  const [tick, setTick] = useState<DashboardTick | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const clientRef = useRef<TickClient | null>(null);

  useEffect(() => {
    const client = new TickClient();
    clientRef.current = client;
    const offTick = client.onTick(setTick);
    const offStatus = client.onStatus(setStatus);
    client.start();
    return () => {
      offTick();
      offStatus();
      client.stop();
    };
  }, []);

  return { tick, status };
}
