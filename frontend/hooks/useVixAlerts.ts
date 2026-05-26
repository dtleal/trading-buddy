"use client";

import { useEffect, useRef } from "react";
import { evaluate, type DeltaState } from "@/lib/alerts/engine";
import { notifyAlert } from "@/lib/alerts/notify";
import { useAlertsStore } from "@/lib/alerts/store";
import type { DashboardTick } from "@/lib/types";

/**
 * Reacts to each new DashboardTick and runs the alert engine.
 *
 * - Keeps the previous tick + delta-rule state in refs (no re-render churn).
 * - Records every fired event in the persistent history store.
 * - Dispatches toast + optional browser notification.
 */
export function useVixAlerts(tick: DashboardTick | null): void {
  const rules = useAlertsStore((s) => s.rules);
  const recordEvent = useAlertsStore((s) => s.recordEvent);
  const desktopEnabled = useAlertsStore((s) => s.notificationsEnabled);

  const prevTickRef = useRef<DashboardTick | null>(null);
  const deltaStateRef = useRef<DeltaState>({});

  useEffect(() => {
    if (!tick) return;
    const prev = prevTickRef.current;

    const { events, deltaState } = evaluate({
      prev,
      next: tick,
      rules,
      deltaState: deltaStateRef.current,
      now: Date.now(),
    });

    deltaStateRef.current = deltaState;
    prevTickRef.current = tick;

    for (const event of events) {
      recordEvent(event);
      notifyAlert(event, desktopEnabled);
    }
  }, [tick, rules, recordEvent, desktopEnabled]);
}
