"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { useAlertsStore } from "@/lib/alerts/store";
import type { Breakout, DashboardTick } from "@/lib/types";

/**
 * Watch the tick stream for newly-emitted Breakout events and dispatch alerts.
 *
 * Backend includes `breakouts_recent` (last ~24h) on every tick — the same
 * breakout shows up in many consecutive ticks. We dedup by `id` so the user
 * only gets one alert per signal. Seen ids are kept in a Set ref to avoid
 * re-firing on re-renders. On a hard reload, history starts fresh — that is
 * fine, the user can scroll the persisted history panel for older events.
 */
export function useBreakoutAlerts(tick: DashboardTick | null): void {
  const seenRef = useRef<Set<string>>(new Set());
  const primedRef = useRef(false);
  const recordEvent = useAlertsStore((s) => s.recordEvent);
  const desktopEnabled = useAlertsStore((s) => s.notificationsEnabled);

  useEffect(() => {
    if (!tick) return;
    const breakouts = tick.breakouts_recent ?? [];

    // Prime the seen set on first tick so we don't alert for everything that
    // happened in the last 24h the moment the page loads.
    if (!primedRef.current) {
      breakouts.forEach((b) => seenRef.current.add(b.id));
      primedRef.current = true;
      return;
    }

    for (const b of breakouts) {
      if (seenRef.current.has(b.id)) continue;
      seenRef.current.add(b.id);
      dispatchBreakoutAlert(b, desktopEnabled);
      recordEvent({
        id: `breakout-${b.id}`,
        ruleId: "breakout",
        ruleKind: "vix_cross", // reuse history panel; not a vix kind but the store accepts the union
        title: titleFor(b),
        detail: detailFor(b),
        tone: toneFor(b),
        firedAt: Date.now(),
      });
    }
  }, [tick, recordEvent, desktopEnabled]);
}

function titleFor(b: Breakout): string {
  const arrow = b.direction === "up" ? "↑" : "↓";
  return `${arrow} ${b.asset} ${b.timeframe} breakout @ ${b.close.toFixed(2)}`;
}

function detailFor(b: Breakout): string {
  const dir = b.direction === "up" ? "rompeu acima" : "rompeu abaixo";
  return `${dir} de ${b.level.toFixed(2)} · expansão ${b.expansion_ratio.toFixed(2)}× ATR · strength ${b.strength.toFixed(0)}/100${b.squeeze ? " · pós-squeeze" : ""}`;
}

function toneFor(b: Breakout): "info" | "warning" | "danger" {
  if (b.strength >= 75) return "danger";
  if (b.strength >= 55) return "warning";
  return "info";
}

function dispatchBreakoutAlert(b: Breakout, desktopEnabled: boolean): void {
  const tone = toneFor(b);
  const fn = tone === "danger" ? toast.error : tone === "warning" ? toast.warning : toast.info;
  fn(titleFor(b), { description: detailFor(b), duration: 10_000 });

  if (
    desktopEnabled &&
    typeof window !== "undefined" &&
    "Notification" in window &&
    Notification.permission === "granted"
  ) {
    try {
      new Notification(titleFor(b), {
        body: detailFor(b),
        tag: `breakout-${b.id}`,
        icon: "/favicon.ico",
      });
    } catch (err) {
      console.warn("Notification dispatch failed", err);
    }
  }
}
