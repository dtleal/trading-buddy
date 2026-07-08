"use client";

import { cn } from "@/lib/utils";
import type { FlowSignal } from "@/lib/types";

/**
 * THE per-asset trade signal, straight off the snapshot's `flow_signal`.
 *
 * This is the exact object the armed scalper bot consumes for its enter /
 * stop-and-reverse decisions (computed once in the backend from the existing
 * scalper + in-trade thresholds), so what this chip shows is what the bot
 * does. Rendered as decision support for manual trading — on quote-only CFD
 * feeds the flow is a synthesized tape, never a recommendation.
 *
 * Tone follows the section's Profit-Trade-like palette: green = buy, red =
 * sell / flow against, amber = take-profit caution, zinc = nothing to do.
 */
export function FlowSignalIndicator({ signal }: { signal: FlowSignal | null }) {
  if (!signal) {
    return (
      <div className="text-[11px] text-zinc-500">Aguardando fluxo para o sinal…</div>
    );
  }

  const s = signal;
  const buy = s.action === "enter_long";
  const sell = s.action === "enter_short";
  const exit = s.action === "exit";
  const urgent = exit && s.basis === "reversal"; // the bot-grade stop-and-reverse
  const softExit = exit && s.basis === "exhaustion";

  const label = buy ? "COMPRA" : sell ? "VENDA" : exit ? "SAIR" : "AGUARDAR";
  const badgeTone = buy
    ? "bg-emerald-500/20 text-emerald-300"
    : sell
      ? "bg-rose-500/20 text-rose-300"
      : softExit
        ? "bg-amber-500/20 text-amber-300"
        : exit
          ? "bg-rose-500/20 text-rose-300"
          : "bg-zinc-700/40 text-zinc-400";
  const barColor = buy
    ? "bg-emerald-500/80"
    : sell || (exit && !softExit)
      ? "bg-rose-500/80"
      : softExit
        ? "bg-amber-500/80"
        : "bg-zinc-600/80";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2">
        <span
          className={cn(
            "rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider",
            badgeTone,
            urgent && "animate-pulse",
          )}
        >
          {label}
        </span>
        <span className="text-[10px] tabular-nums text-zinc-500">
          força {Math.round(s.strength * 100)}%
        </span>
      </div>
      <div className="relative h-1.5 w-full overflow-hidden rounded bg-zinc-800">
        <div
          className={cn("h-full transition-[width] duration-500", barColor)}
          style={{ width: `${Math.round(s.strength * 100)}%` }}
        />
      </div>
      <div className="text-[11px] leading-snug text-zinc-300">{s.reason}</div>
      <div className="text-[10px] text-zinc-500">
        base: {basisLabel(s.basis)} ·{" "}
        {s.basis === "explosion" || s.basis === "reversal"
          ? "o robô armado age neste sinal"
          : "consultivo (o robô não age)"}{" "}
        · apoio à decisão (fluxo sintetizado), não recomendação
      </div>
    </div>
  );
}

function basisLabel(basis: FlowSignal["basis"]): string {
  switch (basis) {
    case "explosion":
      return "explosão (fluxo + range)";
    case "lean":
      return "lean do fluxo";
    case "reversal":
      return "reversão (fluxo contra)";
    case "against":
      return "pressão contrária";
    case "exhaustion":
      return "exaustão do movimento";
    default:
      return "sem leitura";
  }
}
