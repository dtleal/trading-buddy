"use client";

import type { ReactNode } from "react";

import { PlayerRow, money } from "@/components/players/PlayerRow";
import { PlayersFlowChart } from "@/components/players/PlayersFlowChart";
import { cn } from "@/lib/utils";
import type { AssetPlayers } from "@/lib/types";

/** Uma linha de detalhe que reusa as colunas das barras, pra alinhar. */
function DetailLine({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="w-[118px] shrink-0 text-right text-zinc-700">{label}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </div>
  );
}

/** As três linhas grandes. Juntas somam zero: é a partição do pregão. */
const MAIN_ROWS = ["baleia", "banco", "sardinha"] as const;

const GROUP_TONE: Record<string, string> = {
  baleia: "text-sky-400",
  banco: "text-amber-400",
  sardinha: "text-zinc-400",
};

function clock(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(11, 16);
}

/**
 * The Profit tape is written in bursts, not print by print, so "how old is
 * this read" is a number the trader has to see — a green dot that quietly
 * means "três minutos atrás" would be worse than useless.
 */
function freshness(lag: number | null, stale: boolean) {
  if (lag === null) return { label: "sem fita", tone: "bg-zinc-800 text-zinc-400" };
  const text = lag < 90 ? `${lag}s` : `${Math.floor(lag / 60)}m${lag % 60}s`;
  if (stale) return { label: `fita parada · ${text}`, tone: "bg-red-950 text-red-400" };
  if (lag > 60) return { label: `atraso ${text}`, tone: "bg-amber-950 text-amber-400" };
  return { label: `ao vivo · ${text}`, tone: "bg-emerald-950 text-emerald-400" };
}

/** One contract: the player cards, the session shape and who actually traded. */
export function AssetPlayersPanel({ data }: { data: AssetPlayers }) {
  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-zinc-100">{data.asset}</h2>
          <span className="text-[11px] text-zinc-500">{data.symbol}</span>
          {data.last_price !== null && (
            <span className="text-sm font-semibold tabular-nums text-zinc-200">
              {data.last_price.toLocaleString("pt-BR")}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[10px] text-zinc-500">
          <span>
            {data.session} · {clock(data.first_trade)}–{clock(data.last_trade)} ·{" "}
            {data.trades.toLocaleString("pt-BR")} negócios
          </span>
          <span
            className={cn(
              "rounded px-1.5 py-0.5 font-semibold uppercase",
              freshness(data.lag_seconds, data.stale).tone,
            )}
            title="Idade do último negócio lido. O Profit grava o tape em blocos, então esse atraso é dele, não da rede."
          >
            {freshness(data.lag_seconds, data.stale).label}
          </span>
          {data.residual_rs !== 0 && (
            <span
              className="rounded bg-red-950 px-1.5 py-0.5 font-semibold uppercase text-red-400"
              title="Os três grupos têm que somar zero. Sobrou dinheiro = tem corretora fora do mapa."
            >
              resto {money(data.residual_rs)}
            </span>
          )}
        </div>
      </header>

      {/* Três linhas: baleia, banco e sardinha (as duas somadas). O detalhe
          das duas metades da sardinha vem logo abaixo, porque metade é
          marcação da B3 e metade é leitura nossa — a tela tem que dizer isso. */}
      <div className="space-y-1.5">
        {MAIN_ROWS.map((key) => {
          const player = data.players.find((p) => p.key === key);
          return player ? <PlayerRow key={key} player={player} /> : null;
        })}
      </div>

      {/* Duas linhas de detalhe, com as mesmas colunas das barras acima, pra
          tudo cair na mesma régua em vez de flutuar. */}
      <div className="mt-2 space-y-0.5 text-[10px]">
        <DetailLine label="RLP (varejo B3)">
          {(() => {
            const rlp = data.players.find((p) => p.key === "rlp");
            if (!rlp) return null;
            return (
              <span className="whitespace-nowrap">
                <span className={rlp.saldo_rs >= 0 ? "text-sky-500" : "text-red-500"}>
                  {money(rlp.saldo_rs)}
                </span>
                <span className="ml-2 text-zinc-700">
                  negócio internalizado pela corretora, fora do book — é a única
                  parte que a B3 marca como varejo
                </span>
              </span>
            );
          })()}
        </DetailLine>
        <DetailLine label="últimos 15 min">
          {MAIN_ROWS.map((key) => {
            const player = data.players.find((p) => p.key === key);
            if (!player) return null;
            return (
              <span key={key} className="mr-4 whitespace-nowrap">
                <span className="text-zinc-600">{player.label.toLowerCase()} </span>
                <span
                  className={player.saldo_recente_rs >= 0 ? "text-sky-500" : "text-red-500"}
                >
                  {money(player.saldo_recente_rs)}
                </span>
              </span>
            );
          })}
        </DetailLine>
      </div>

      <div className="mt-4">
        <PlayersFlowChart series={data.series} />
      </div>

      <details className="mt-3">
        <summary className="cursor-pointer text-[11px] text-zinc-500 hover:text-zinc-300">
          quem girou o dia (top 12 corretoras)
        </summary>
        <table className="mt-2 w-full text-[11px]">
          <thead className="text-zinc-600">
            <tr>
              <th className="py-1 text-left font-normal">corretora</th>
              <th className="py-1 text-left font-normal">grupo</th>
              <th className="py-1 text-right font-normal">giro</th>
              <th className="py-1 text-right font-normal">saldo</th>
            </tr>
          </thead>
          <tbody className="text-zinc-400">
            {data.top_brokers.map((broker) => (
              <tr key={broker.code} className="border-t border-zinc-900">
                <td className="py-1">{broker.name}</td>
                <td className={cn("py-1", GROUP_TONE[broker.grupo] ?? "text-zinc-500")}>
                  {broker.grupo}
                </td>
                <td className="py-1 text-right tabular-nums">
                  {broker.volume.toLocaleString("pt-BR")}
                </td>
                <td
                  className={cn(
                    "py-1 text-right tabular-nums",
                    broker.saldo > 0 ? "text-sky-400" : broker.saldo < 0 ? "text-red-400" : "",
                  )}
                >
                  {broker.saldo > 0 ? "+" : ""}
                  {broker.saldo.toLocaleString("pt-BR")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
