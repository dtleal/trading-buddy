"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { playAlertSound } from "@/lib/alerts/sound";
import { useAlertsStore } from "@/lib/alerts/store";
import type { Breakout, DashboardTick } from "@/lib/types";
import { fmtPrice, priceDigits } from "@/lib/utils";

// How recent a breakout has to be (in minutes) to still trigger an alert when
// it first shows up after the page loads. Older signals get silently primed
// so the user doesn't get spammed with stale alerts. 5 minutes covers "the
// breakout happened seconds before I opened the dashboard" — exactly the
// case we want to keep loud.
const ALERT_FRESHNESS_MINUTES = 5;

/**
 * Watch the tick stream for newly-emitted Breakout events and dispatch alerts.
 *
 * Backend includes `breakouts_recent` (last ~24h) on every tick — the same
 * breakout shows up in many consecutive ticks. We dedup by `id`. On first
 * tick we **only prime stale signals** (older than ALERT_FRESHNESS_MINUTES);
 * anything fresh fires as a real alert so the trader who just walked up to
 * the dashboard doesn't miss the last-5-min move that motivated them.
 */
export function useBreakoutAlerts(tick: DashboardTick | null): void {
  const seenRef = useRef<Set<string>>(new Set());
  const primedRef = useRef(false);
  const recordEvent = useAlertsStore((s) => s.recordEvent);
  const desktopEnabled = useAlertsStore((s) => s.notificationsEnabled);
  const soundEnabled = useAlertsStore((s) => s.soundEnabled);

  useEffect(() => {
    if (!tick) return;
    const breakouts = tick.breakouts_recent ?? [];

    if (!primedRef.current) {
      const freshnessMs = ALERT_FRESHNESS_MINUTES * 60_000;
      const now = Date.now();
      for (const b of breakouts) {
        const ageMs = now - new Date(b.signal_bar_at).getTime();
        // Stale → mark as seen (no alert). Fresh → leave unseen so the loop
        // below treats it as a brand-new event.
        if (ageMs > freshnessMs) {
          seenRef.current.add(b.id);
        }
      }
      primedRef.current = true;
      // Fall through to the dispatch loop — recent ones still need alerting.
    }

    for (const b of breakouts) {
      if (seenRef.current.has(b.id)) continue;
      seenRef.current.add(b.id);
      dispatchBreakoutAlert(b, desktopEnabled, soundEnabled);
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
  }, [tick, recordEvent, desktopEnabled, soundEnabled]);
}

function titleFor(b: Breakout): string {
  const arrow = b.direction === "up" ? "↑" : "↓";
  return `${arrow} ${b.asset} ${b.timeframe} breakout @ ${fmtPrice(b.close)}`;
}

function detailFor(b: Breakout): string {
  const dir = b.direction === "up" ? "rompeu acima" : "rompeu abaixo";
  return `${dir} de ${fmtPrice(b.level, priceDigits(b.close))} · expansão ${b.expansion_ratio.toFixed(2)}× ATR · strength ${b.strength.toFixed(0)}/100${b.squeeze ? " · pós-squeeze" : ""}`;
}

function toneFor(b: Breakout): "info" | "warning" | "danger" {
  if (b.strength >= 75) return "danger";
  if (b.strength >= 55) return "warning";
  return "info";
}

function dispatchBreakoutAlert(b: Breakout, desktopEnabled: boolean, soundEnabled: boolean): void {
  const tone = toneFor(b);
  const fn = tone === "danger" ? toast.error : tone === "warning" ? toast.warning : toast.info;
  fn(titleFor(b), { description: detailFor(b), duration: 10_000 });

  if (soundEnabled) playAlertSound(tone);

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
