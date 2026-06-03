/**
 * Zustand store for alert rules + history.
 *
 * Persisted in localStorage so the user's configuration survives reloads.
 * History is capped at MAX_HISTORY entries to keep storage small.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { AlertEvent, AlertRule } from "./types";

const MAX_HISTORY = 100;

const DEFAULT_RULES: AlertRule[] = [
  {
    id: "default-cross-20",
    kind: "vix_cross",
    level: 20,
    direction: "up",
    enabled: true,
  },
  {
    id: "default-cross-25",
    kind: "vix_cross",
    level: 25,
    direction: "up",
    enabled: true,
  },
  {
    id: "default-regime-change",
    kind: "regime_change",
    enabled: true,
  },
  {
    id: "default-term-flip",
    kind: "term_flip",
    to: "backwardation",
    enabled: true,
  },
  {
    id: "default-delta-10",
    kind: "vix_delta",
    pct_change: 10,
    window_seconds: 15 * 60,
    enabled: true,
  },
];

interface AlertsState {
  rules: AlertRule[];
  history: AlertEvent[];
  notificationsEnabled: boolean;
  soundEnabled: boolean;

  addRule: (rule: AlertRule) => void;
  updateRule: (id: string, patch: Partial<AlertRule>) => void;
  removeRule: (id: string) => void;
  toggleRule: (id: string) => void;

  recordEvent: (event: AlertEvent) => void;
  clearHistory: () => void;

  setNotificationsEnabled: (enabled: boolean) => void;
  setSoundEnabled: (enabled: boolean) => void;
}

export const useAlertsStore = create<AlertsState>()(
  persist(
    (set) => ({
      rules: DEFAULT_RULES,
      history: [],
      notificationsEnabled: false,
      soundEnabled: true,

      addRule: (rule) => set((s) => ({ rules: [...s.rules, rule] })),
      updateRule: (id, patch) =>
        set((s) => ({
          rules: s.rules.map((r) =>
            r.id === id ? ({ ...r, ...patch } as AlertRule) : r,
          ),
        })),
      removeRule: (id) =>
        set((s) => ({ rules: s.rules.filter((r) => r.id !== id) })),
      toggleRule: (id) =>
        set((s) => ({
          rules: s.rules.map((r) =>
            r.id === id ? ({ ...r, enabled: !r.enabled } as AlertRule) : r,
          ),
        })),

      recordEvent: (event) =>
        set((s) => ({
          history: [event, ...s.history].slice(0, MAX_HISTORY),
        })),
      clearHistory: () => set({ history: [] }),

      setNotificationsEnabled: (enabled) => set({ notificationsEnabled: enabled }),
      setSoundEnabled: (enabled) => set({ soundEnabled: enabled }),
    }),
    {
      name: "trading-buddy-alerts",
      version: 1,
    },
  ),
);
