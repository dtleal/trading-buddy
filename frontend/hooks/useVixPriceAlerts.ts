"use client";

import { useEffect, useRef } from "react";
import { notifyAlert } from "@/lib/alerts/notify";
import { useAlertsStore } from "@/lib/alerts/store";
import type { AlertEvent } from "@/lib/alerts/types";
import type { DashboardTick, VixPriceSignal } from "@/lib/types";

const STANCE_LABEL: Record<VixPriceSignal["stance"], string> = {
  sell_rallies: "só VENDA em repique",
  buy_dips: "COMPRE recuos",
  stay_out: "fique de FORA",
  neutral: "neutro",
};

const CAUTION_LABEL: Record<NonNullable<VixPriceSignal["caution"]>, string> = {
  exit_longs: "considere ENCERRAR compras",
  exit_shorts: "considere ENCERRAR vendas",
};

/**
 * Fires toast + sound + desktop notification when a VIX×price stance changes
 * or when price reaches the actionable Bollinger zone ("zona AGORA").
 *
 * Edge-triggered on both: the first tick after load only seeds the refs (no
 * alert storm on refresh), and the trigger only fires on false→true.
 */
export function useVixPriceAlerts(tick: DashboardTick | null): void {
  const recordEvent = useAlertsStore((s) => s.recordEvent);
  const desktopEnabled = useAlertsStore((s) => s.notificationsEnabled);
  const soundEnabled = useAlertsStore((s) => s.soundEnabled);

  const prevStateRef = useRef<Record<string, string> | null>(null);
  const prevTriggerRef = useRef<Record<string, boolean>>({});

  useEffect(() => {
    if (!tick) return;
    const signals = Object.values(tick.vix_price ?? {});
    const seeding = prevStateRef.current === null;
    const prevState = prevStateRef.current ?? {};
    const prevTrigger = prevTriggerRef.current;

    const nextState: Record<string, string> = {};
    const nextTrigger: Record<string, boolean> = {};

    for (const sig of signals) {
      const state = `${sig.stance}:${sig.caution ?? "-"}`;
      nextState[sig.asset] = state;
      nextTrigger[sig.asset] = sig.trigger;
      if (seeding) continue;

      const actionable = sig.stance !== "neutral" || sig.caution != null;
      if (prevState[sig.asset] !== state && actionable) {
        fire({
          id: `vix_price-${sig.asset}-${Date.now()}`,
          ruleId: `vix_price:${sig.asset}`,
          ruleKind: "vix_price",
          title: sig.caution
            ? `⚠️ ${sig.asset}: ${CAUTION_LABEL[sig.caution]}`
            : `${sig.asset}: ${STANCE_LABEL[sig.stance]}`,
          detail: sig.headline,
          tone: sig.caution ? "danger" : sig.stance === "buy_dips" ? "info" : "warning",
          firedAt: Date.now(),
        });
      }

      const inZone =
        sig.trigger && !prevTrigger[sig.asset] &&
        (sig.stance === "sell_rallies" || sig.stance === "buy_dips");
      if (inZone) {
        fire({
          id: `vix_price_zone-${sig.asset}-${Date.now()}`,
          ruleId: `vix_price_zone:${sig.asset}`,
          ruleKind: "vix_price",
          title: `🎯 ${sig.asset}: zona de ${sig.stance === "sell_rallies" ? "VENDA" : "COMPRA"} agora`,
          detail: sig.headline,
          tone: sig.stance === "sell_rallies" ? "danger" : "info",
          firedAt: Date.now(),
        });
      }
    }

    prevStateRef.current = nextState;
    prevTriggerRef.current = nextTrigger;

    function fire(event: AlertEvent) {
      recordEvent(event);
      notifyAlert(event, desktopEnabled, soundEnabled);
    }
  }, [tick, recordEvent, desktopEnabled, soundEnabled]);
}
