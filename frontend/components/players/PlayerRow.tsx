"use client";

import { cn } from "@/lib/utils";
import type { PlayerRead } from "@/lib/types";

export const MASCOT: Record<string, string> = {
  baleia: "🐳",
  banco: "🏛️",
  sardinha: "🐟",
  varejo: "👤",
};

export const LABEL_TONE: Record<string, string> = {
  baleia: "text-sky-400",
  banco: "text-amber-400",
  sardinha: "text-zinc-300",
  varejo: "text-zinc-300",
};

/**
 * Money the way the reference desk screen writes it: the whole number, then
 * the unit word. "R$ 1.103.360.848 bi" is redundant read literally, but it is
 * the shape the user reads all day, and the complaint that started this was
 * exactly "faltando dizer se é mi ou bi".
 */
export type Currency = "BRL" | "USD";

const MONEY: Record<Currency, Intl.NumberFormat> = {
  BRL: new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 }),
  USD: new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", maximumFractionDigits: 0 }),
};

export function money(value: number, currency: Currency = "BRL"): string {
  const size = Math.abs(value);
  const suffix = size >= 1e9 ? " bi" : size >= 1e6 ? " mi" : "";
  return MONEY[currency].format(value) + suffix;
}

/**
 * One player group, laid out like the reference: who on the left, the money on
 * a full-width coloured bar in the middle, what it is doing on the right.
 *
 * The bar is solid rather than filled by strength, on purpose — this is meant
 * to be read at a glance from across the desk, and a half-filled bar reads as
 * "half" rather than "less pressure". The strength number lives in the title.
 */
export function PlayerRow({
  player,
  count,
  currency = "BRL",
}: {
  player: PlayerRead;
  count?: boolean;
  currency?: Currency;
}) {
  const bought = player.saldo_rs >= 0;
  const flat = player.saldo_rs === 0;
  const bar = flat ? "bg-zinc-800" : bought ? "bg-blue-800" : "bg-red-700";
  const tone = flat ? "text-zinc-300" : bought ? "text-sky-400" : "text-red-400";

  return (
    <div className="flex items-center gap-3">
      <div className="flex w-[118px] shrink-0 items-center gap-2">
        <span aria-hidden className="text-base leading-none">
          {MASCOT[player.key] ?? "•"}
        </span>
        <span className={cn("text-[12px] font-bold tracking-wide", LABEL_TONE[player.key])}>
          {player.label}
        </span>
      </div>

      <div
        className={cn("flex h-7 min-w-0 flex-1 items-center justify-center rounded-sm", bar)}
        title={
          `${player.volume.toLocaleString("pt-BR")} contratos girados · ` +
          `força ${player.forca_pct}% · agrediu ${player.agressao_pct}%`
        }
      >
        <span className="text-[13px] font-bold tabular-nums text-white">
          {money(player.saldo_rs, currency)}
          {/* A linha do varejo mostra o número de contratos junto: é a conta
              que o usuário faz em cima dela ("estou contra quantos?"). */}
          {count && (
            <span className="ml-2 font-normal opacity-80">
              {player.saldo > 0 ? "+" : ""}
              {player.saldo.toLocaleString("pt-BR")} contratos
            </span>
          )}
        </span>
      </div>

      <div className="flex shrink-0 items-baseline whitespace-nowrap text-[11px] font-semibold uppercase tracking-wide">
        <span className={cn("w-[80px] text-left", tone)}>
          {bought ? "COMPRADO" : "VENDIDO"}
        </span>
      </div>
    </div>
  );
}
