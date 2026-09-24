"use client";

import type { AgendaAlert as Alert } from "@/hooks/useAgenda";

/** Faixa amarela embaixo da tela (a de agressão fica em cima, pra não brigar). */
export function AgendaAlert({ alert, onDismiss }: { alert: Alert; onDismiss: () => void }) {
  const hora = new Date(alert.event.at).toLocaleTimeString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <button
      type="button"
      onClick={onDismiss}
      title="clique pra fechar"
      className="fixed inset-x-0 bottom-0 z-50 w-full border-t-4 border-amber-400 bg-amber-950/95 px-4 py-3 text-left text-amber-100"
    >
      <div className="mx-auto flex w-full max-w-[2100px] flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-3xl font-black uppercase tracking-tight">
          ⚠ Notícia em {alert.minutes} min
        </span>
        <span className="text-2xl font-bold">
          {alert.event.country} · {alert.event.title}
        </span>
        <span className="text-base tabular-nums opacity-80">
          {hora} · {alert.event.source}
        </span>
      </div>
    </button>
  );
}
