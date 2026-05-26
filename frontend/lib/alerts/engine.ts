/**
 * Stateless evaluator: given a previous tick + a new tick + the user's rules,
 * return the events that fire. Pure function for testability.
 *
 * Delta-rule reference values are tracked per-rule in a small map maintained
 * by the caller (the React hook). This keeps the engine pure.
 */
import type { DashboardTick } from "@/lib/types";
import type {
  AlertEvent,
  AlertRule,
  VixCrossRule,
  VixDeltaRule,
  VixRegimeChangeRule,
  VixTermFlipRule,
} from "./types";

export type DeltaState = Record<string, { ref: number; refAt: number }>;

export interface EvaluateInput {
  prev: DashboardTick | null;
  next: DashboardTick;
  rules: AlertRule[];
  deltaState: DeltaState;
  now: number;
}

export interface EvaluateOutput {
  events: AlertEvent[];
  deltaState: DeltaState;
}

export function evaluate({ prev, next, rules, deltaState, now }: EvaluateInput): EvaluateOutput {
  const events: AlertEvent[] = [];
  const nextDelta: DeltaState = { ...deltaState };

  for (const rule of rules) {
    if (!rule.enabled) continue;
    switch (rule.kind) {
      case "vix_cross": {
        const ev = evalCross(rule, prev, next, now);
        if (ev) events.push(ev);
        break;
      }
      case "regime_change": {
        const ev = evalRegime(rule, prev, next, now);
        if (ev) events.push(ev);
        break;
      }
      case "term_flip": {
        const ev = evalTerm(rule, prev, next, now);
        if (ev) events.push(ev);
        break;
      }
      case "vix_delta": {
        const result = evalDelta(rule, next, nextDelta[rule.id], now);
        nextDelta[rule.id] = result.state;
        if (result.event) events.push(result.event);
        break;
      }
    }
  }

  return { events, deltaState: nextDelta };
}

// ---------- evaluators ----------

function evalCross(
  rule: VixCrossRule,
  prev: DashboardTick | null,
  next: DashboardTick,
  now: number,
): AlertEvent | null {
  if (!prev) return null;
  const before = prev.market.vix.vix;
  const after = next.market.vix.vix;
  const level = rule.level;
  const wentUp = before < level && after >= level;
  const wentDown = before > level && after <= level;
  const fires =
    (rule.direction === "up" && wentUp) ||
    (rule.direction === "down" && wentDown) ||
    (rule.direction === "either" && (wentUp || wentDown));
  if (!fires) return null;
  const direction = wentUp ? "subiu" : "caiu";
  return {
    id: `${rule.id}-${now}`,
    ruleId: rule.id,
    ruleKind: rule.kind,
    title: `VIX ${direction} de ${before.toFixed(2)} → ${after.toFixed(2)}`,
    detail: `Cruzou o nível ${level} (${rule.direction === "either" ? "qualquer direção" : rule.direction === "up" ? "alta" : "queda"}).`,
    tone: level >= 20 ? "danger" : "warning",
    firedAt: now,
  };
}

function evalRegime(
  rule: VixRegimeChangeRule,
  prev: DashboardTick | null,
  next: DashboardTick,
  now: number,
): AlertEvent | null {
  if (!prev) return null;
  const before = prev.market.vix.regime;
  const after = next.market.vix.regime;
  if (before === after) return null;
  if (rule.to && after !== rule.to) return null;
  return {
    id: `${rule.id}-${now}`,
    ruleId: rule.id,
    ruleKind: rule.kind,
    title: `Regime VIX: ${before} → ${after}`,
    detail: rule.to
      ? `Entrou em "${rule.to}" como configurado.`
      : "Mudança de regime detectada.",
    tone: after === "high" ? "danger" : after === "low" ? "info" : "warning",
    firedAt: now,
  };
}

function evalTerm(
  rule: VixTermFlipRule,
  prev: DashboardTick | null,
  next: DashboardTick,
  now: number,
): AlertEvent | null {
  if (!prev) return null;
  const before = prev.market.vix.term_structure;
  const after = next.market.vix.term_structure;
  if (before === after) return null;
  if (rule.to && after !== rule.to) return null;
  return {
    id: `${rule.id}-${now}`,
    ruleId: rule.id,
    ruleKind: rule.kind,
    title: `Term structure: ${before} → ${after}`,
    detail:
      after === "backwardation"
        ? "Curva invertida — sinal clássico de stress de curto prazo."
        : `Curva agora em ${after}.`,
    tone: after === "backwardation" ? "danger" : "info",
    firedAt: now,
  };
}

function evalDelta(
  rule: VixDeltaRule,
  next: DashboardTick,
  state: { ref: number; refAt: number } | undefined,
  now: number,
): { event: AlertEvent | null; state: { ref: number; refAt: number } } {
  const v = next.market.vix.vix;
  // Initialize the reference on first sight.
  if (!state) return { event: null, state: { ref: v, refAt: now } };

  // Reset the reference if the window has elapsed.
  const windowMs = rule.window_seconds * 1000;
  if (now - state.refAt > windowMs) {
    return { event: null, state: { ref: v, refAt: now } };
  }

  const pct = ((v - state.ref) / state.ref) * 100;
  if (Math.abs(pct) < rule.pct_change) {
    return { event: null, state };
  }

  // Fire — and roll the reference forward so the same move doesn't keep firing.
  return {
    event: {
      id: `${rule.id}-${now}`,
      ruleId: rule.id,
      ruleKind: rule.kind,
      title: `VIX moveu ${pct >= 0 ? "+" : ""}${pct.toFixed(1)}% em ${Math.round(rule.window_seconds / 60)}min`,
      detail: `Referência: ${state.ref.toFixed(2)} → atual ${v.toFixed(2)} (limite configurado: ${rule.pct_change}%).`,
      tone: Math.abs(pct) >= 15 ? "danger" : "warning",
      firedAt: now,
    },
    state: { ref: v, refAt: now },
  };
}
