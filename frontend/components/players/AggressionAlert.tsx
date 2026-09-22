"use client";

import { cn } from "@/lib/utils";
import type { AggressionAlert as Alert } from "@/hooks/useAggressionAlert";

/**
 * O aviso de agressão nova, em cima de tudo.
 *
 * Grande de propósito: a tela fica num monitor de lado, e o ponto do card de
 * agressões é justamente não depender de alguém estar olhando pra tabela na
 * hora. Some sozinho depois de 20s, e sai no clique.
 */
export function AggressionAlert({ alert, onDismiss }: { alert: Alert; onDismiss: () => void }) {
  const bought = alert.lado === "COMPRA";
  const move = alert.price_to - alert.price_from;

  return (
    <button
      type="button"
      onClick={onDismiss}
      title="clique pra fechar"
      className={cn(
        "fixed inset-x-0 top-0 z-50 w-full border-b-4 px-4 py-3 text-left",
        bought
          ? "border-sky-400 bg-sky-950/95 text-sky-100"
          : "border-red-400 bg-red-950/95 text-red-100",
      )}
    >
      <div className="mx-auto flex w-full max-w-[2100px] flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-3xl font-black uppercase tracking-tight">
          {bought ? "▲" : "▼"} {alert.agressor} {bought ? "COMPRANDO" : "VENDENDO"}
        </span>
        <span className="text-2xl font-bold tabular-nums">
          {alert.qty.toLocaleString("pt-BR")} {alert.asset}
        </span>
        <span className="text-base tabular-nums opacity-80">
          {alert.price_from.toLocaleString("pt-BR")} →{" "}
          {alert.price_to.toLocaleString("pt-BR")} ({move > 0 ? "+" : ""}
          {move.toLocaleString("pt-BR")}) · méd {alert.price_avg.toLocaleString("pt-BR")} ·{" "}
          {alert.at.slice(11, 16)}
        </span>
      </div>
    </button>
  );
}
