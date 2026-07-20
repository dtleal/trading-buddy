/**
 * VIX alert types.
 *
 * Each rule is a discriminated union — `kind` selects the evaluator. New rule
 * shapes get a new branch + a new case in `lib/alerts/engine.ts`.
 */
import type { VixRegime, TermStructure } from "@/lib/types";

export type VixCrossRule = {
  id: string;
  kind: "vix_cross";
  /** Trigger when crossing this level, in either direction (configurable). */
  level: number;
  direction: "up" | "down" | "either";
  enabled: boolean;
};

export type VixRegimeChangeRule = {
  id: string;
  kind: "regime_change";
  /** If unset, any regime change fires. */
  to?: VixRegime;
  enabled: boolean;
};

export type VixTermFlipRule = {
  id: string;
  kind: "term_flip";
  /** If unset, any term change fires. */
  to?: TermStructure;
  enabled: boolean;
};

export type VixDeltaRule = {
  id: string;
  kind: "vix_delta";
  /** Trigger when the VIX moves at least this % since the rule's reference value. */
  pct_change: number;
  /** Sliding-window reference: how often (sec) the reference resets. */
  window_seconds: number;
  enabled: boolean;
};

export type AlertRule =
  | VixCrossRule
  | VixRegimeChangeRule
  | VixTermFlipRule
  | VixDeltaRule;

export type AlertTone = "info" | "warning" | "danger";

export type AlertEvent = {
  id: string;
  ruleId: string;
  ruleKind: AlertRule["kind"] | "level_proximity";
  title: string;
  detail: string;
  tone: AlertTone;
  /** UNIX millis */
  firedAt: number;
};
