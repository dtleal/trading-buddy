"use client";

import { useEffect, useRef } from "react";
import { notifyAlert } from "@/lib/alerts/notify";
import { useAlertsStore } from "@/lib/alerts/store";
import { fmtPrice } from "@/lib/utils";
import type { AlertEvent } from "@/lib/alerts/types";
import type { LevelProximity, ProximityTier } from "@/lib/alerts/levels";

const TIER_RANK: Record<ProximityTier, number> = { none: 0, near: 1, at: 2 };

/**
 * Fires a loud alert (toast + sound + optional desktop notification) when a
 * symbol's live price approaches — then reaches/breaks — yesterday's high/low.
 *
 * Edge-triggered per symbol+level: it fires once when the tier *escalates*
 * (none→near→at) so a hovering price near the level doesn't spam every tick.
 * When the price backs away the stored tier falls with it, so a later approach
 * re-arms the alert.
 */
export function useLevelAlerts(proximities: LevelProximity[]): void {
  const recordEvent = useAlertsStore((s) => s.recordEvent);
  const desktopEnabled = useAlertsStore((s) => s.notificationsEnabled);
  const soundEnabled = useAlertsStore((s) => s.soundEnabled);

  // key = `${symbol}:${kind}` → last tier we saw for that level.
  const lastTierRef = useRef<Record<string, ProximityTier>>({});

  useEffect(() => {
    const seen = new Set<string>();

    for (const p of proximities) {
      const key = `${p.symbol}:${p.kind}`;
      seen.add(key);
      const prev = lastTierRef.current[key] ?? "none";
      lastTierRef.current[key] = p.tier;

      // Only fire on escalation (near→at or none→near/at).
      if (TIER_RANK[p.tier] <= TIER_RANK[prev]) continue;

      const now = Date.now();
      const levelName = p.kind === "PDH" ? "máxima de ontem" : "mínima de ontem";
      const atLevel = p.tier === "at";
      const event: AlertEvent = {
        id: `lvl-${key}-${p.tier}-${now}`,
        ruleId: `level-${key}`,
        ruleKind: "level_proximity",
        title: atLevel
          ? `${p.label} ${p.broken ? "rompeu" : "NA"} ${levelName} (${p.kind})`
          : `${p.label} chegando na ${levelName} (${p.kind})`,
        detail: `Preço ${fmtPrice(p.price)} · ${p.kind} ${fmtPrice(p.target)} · ${
          p.gap > 0 ? `${fmtPrice(Math.abs(p.gap))} pts para o nível` : "nível rompido"
        }`,
        tone: atLevel ? "danger" : "warning",
        firedAt: now,
      };
      recordEvent(event);
      notifyAlert(event, desktopEnabled, soundEnabled);
    }

    // Drop levels no longer present so they can re-arm cleanly.
    for (const key of Object.keys(lastTierRef.current)) {
      if (!seen.has(key)) delete lastTierRef.current[key];
    }
  }, [proximities, recordEvent, desktopEnabled, soundEnabled]);
}
