"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { LABEL_TONE, MASCOT, PlayerRow, money } from "@/components/players/PlayerRow";
import { Aggressions } from "@/components/players/Aggressions";
import { PlayersFlowChart } from "@/components/players/PlayersFlowChart";
import { cn } from "@/lib/utils";
import type { AssetPlayers, PlayerRead, PlayersTick } from "@/lib/types";

/** Uma linha de detalhe que reusa as colunas das barras, pra alinhar. */
function DetailLine({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="w-[118px] shrink-0 text-right text-zinc-400">{label}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </div>
  );
}

/** As três linhas grandes. Juntas somam zero: é a partição do pregão. */
const MAIN_ROWS = ["baleia", "banco", "sardinha"] as const;

/**
 * A quarta linha: o varejo inteiro, sardinha (foi pro book) + RLP (a corretora
 * executou por dentro). São dois caminhos da mesma pessoa, e sem somar não dá
 * pra responder "o que o CPF fez hoje" sem fazer conta de cabeça.
 *
 * Não entra na partição — os três de cima é que somam zero. Esta é uma leitura
 * em cima deles, e as duas metades nem têm a mesma força: sardinha é leitura do
 * nome da corretora, RLP é marcação da B3 com a direção estimada pelo tique.
 */
function varejoRow(players: PlayerRead[]): PlayerRead | null {
  const book = players.find((p) => p.key === "sardinha");
  const rlp = players.find((p) => p.key === "rlp");
  if (!book || !rlp) return null;
  return {
    ...book,
    key: "varejo",
    label: "VAREJO",
    papel: "sardinha + rlp",
    saldo_rs: book.saldo_rs + rlp.saldo_rs,
    saldo_recente_rs: book.saldo_recente_rs + rlp.saldo_recente_rs,
    saldo: book.saldo + rlp.saldo,
    saldo_recente: book.saldo_recente + rlp.saldo_recente,
    volume: book.volume + rlp.volume,
    volume_rs: book.volume_rs + rlp.volume_rs,
  };
}

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
type Grupo = "todos" | "baleia" | "banco" | "sardinha";
type Lado = "todos" | "comprado" | "vendido";
type Ordem = "corretora" | "grupo" | "giro" | "saldo";

/** Filtros do card das corretoras. Ficam no card, e não na barra do topo, porque
 *  é uma pergunta por ativo: "quem girou o WIN" é outra lista de "quem girou o
 *  WDO". */
function BrokerFilters({
  grupo,
  lado,
  ordem,
  onGrupo,
  onLado,
  onOrdem,
}: {
  grupo: Grupo;
  lado: Lado;
  ordem: Ordem;
  onGrupo: (value: Grupo) => void;
  onLado: (value: Lado) => void;
  onOrdem: (value: Ordem) => void;
}) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
      <Chips
        options={["todos", "baleia", "banco", "sardinha"] as const}
        value={grupo}
        onChange={onGrupo}
      />
      <Chips options={["todos", "comprado", "vendido"] as const} value={lado} onChange={onLado} />
      <div className="flex items-center gap-1">
        <span className="text-zinc-400">ordem</span>
        <Chips options={["giro", "saldo"] as const} value={ordem} onChange={onOrdem} />
      </div>
    </div>
  );
}

/** Título de coluna que ordena a tabela. A seta mostra por onde está ordenado,
 *  que é a única forma de a lista não parecer embaralhada depois do clique. */
function SortHeader({
  coluna,
  ordem,
  desc,
  onSort,
  align = "left",
}: {
  coluna: Ordem;
  ordem: Ordem;
  desc: boolean;
  onSort: (coluna: Ordem) => void;
  align?: "left" | "right";
}) {
  const active = coluna === ordem;
  return (
    <th className={cn("py-1 font-normal", align === "right" ? "text-right" : "text-left")}>
      <button
        type="button"
        onClick={() => onSort(coluna)}
        className={cn("hover:text-zinc-300", active && "text-zinc-300")}
      >
        {coluna}
        <span className="ml-0.5 text-[11px]">{active ? (desc ? "▼" : "▲") : ""}</span>
      </button>
    </th>
  );
}

function Chips<T extends string>({
  options,
  value,
  onChange,
}: {
  options: readonly T[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex gap-1">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          className={cn(
            "rounded px-1.5 py-[2px]",
            option === value
              ? "bg-zinc-800 text-zinc-200"
              : "text-zinc-400 hover:text-zinc-400",
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

/** Na CME os grupos saem do tamanho do lote (a fita é anônima), não há RLP
 *  nem corretora, e o dinheiro é em dólar. */
const CME_CUT =
  "Mesmo grupo de lote, mesmo lado, dentro de 2 minutos. Corte: 150 contratos no GC e no NQ, 400 no ES.";

export function AssetPlayersPanel({
  data,
  tick,
  cme,
}: {
  data: AssetPlayers;
  tick?: PlayersTick;
  cme?: boolean;
}) {
  const currency = cme ? "USD" : "BRL";
  // O tick chega 10x por segundo e traz só preço, hora e contagem; o resto do
  // card continua vindo da leitura inteira.
  const price = tick?.last_price ?? data.last_price;
  const lastTrade = tick?.last_trade ?? data.last_trade;
  const trades = tick?.trades ?? data.trades;
  const [grupo, setGrupo] = useState<Grupo>("todos");
  const [lado, setLado] = useState<Lado>("todos");
  const [ordem, setOrdem] = useState<Ordem>("giro");
  const [desc, setDesc] = useState(true);

  // Clicar de novo no mesmo título inverte; trocar de coluna começa do maior,
  // que é o que se quer ver em giro e saldo.
  const sortBy = (coluna: Ordem) => {
    setDesc(coluna === ordem ? !desc : true);
    setOrdem(coluna);
  };

  // A lista vem do backend já ordenada por giro e cortada no top 12, então
  // filtrar e ordenar aqui é só mexer no que já está na tela — nada volta pro
  // servidor.
  const brokers = useMemo(() => {
    const rows = data.top_brokers.filter(
      (broker) =>
        (grupo === "todos" || broker.grupo === grupo) &&
        (lado === "todos" ||
          (lado === "comprado" ? broker.saldo > 0 : broker.saldo < 0)),
    );
    const order = desc ? -1 : 1;
    return [...rows].sort((a, b) => {
      if (ordem === "corretora") return order * a.name.localeCompare(b.name);
      if (ordem === "grupo") return order * a.grupo.localeCompare(b.grupo);
      if (ordem === "saldo") return order * (a.saldo - b.saldo);
      return order * (a.volume - b.volume);
    });
  }, [data.top_brokers, grupo, lado, ordem, desc]);

  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-zinc-100">{data.asset}</h2>
          <span className="text-[11px] text-zinc-300">{data.symbol}</span>
          {data.live && (
            <span
              className="rounded bg-emerald-950 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-emerald-400"
              title="Negócio a negócio pelo RTD do Profit, sem esperar o arquivo gravar."
            >
              RTD
            </span>
          )}
          {price !== null && (
            <span className="text-sm font-semibold tabular-nums text-zinc-200">
              {price.toLocaleString("pt-BR")}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-[11px] text-zinc-300">
          <span>
            {data.session} · {clock(data.first_trade)}–{clock(lastTrade)} ·{" "}
            {trades.toLocaleString("pt-BR")} negócios
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
          return player ? <PlayerRow key={key} player={player} currency={currency} /> : null;
        })}
        {(() => {
          const varejo = varejoRow(data.players);
          return varejo ? <PlayerRow player={varejo} count /> : null;
        })()}
      </div>

      {/* Duas linhas de detalhe, com as mesmas colunas das barras acima, pra
          tudo cair na mesma régua em vez de flutuar. */}
      {!cme && (
      <div className="mt-2 space-y-0.5 text-[11px]">
        <DetailLine label="RLP (varejo B3)">
          {(() => {
            const rlp = data.players.find((p) => p.key === "rlp");
            if (!rlp) return null;
            return (
              <span className="whitespace-nowrap">
                <span className={rlp.saldo_rs >= 0 ? "text-sky-500" : "text-red-500"}>
                  {money(rlp.saldo_rs)}
                </span>
                <span className="ml-2 text-zinc-400">
                  negócio internalizado pela corretora, fora do book — é a única
                  parte que a B3 marca como varejo
                </span>
              </span>
            );
          })()}
        </DetailLine>
      </div>
      )}

      {/* Os últimos 15 minutos estavam numa linha só, em 10px cinza escuro, com
          os três grupos espremidos — ilegível. Agora é uma coluna por grupo, na
          mesma régua das barras, com o mesmo bicho e a mesma cor de cima pra
          não ter que reler quem é quem. */}
      <div className="mt-3 flex items-stretch gap-3">
        <div className="flex w-[118px] shrink-0 flex-col justify-center">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
            últimos 15 min
          </span>
          <span className="text-[11px] text-zinc-400">o que está fazendo agora</span>
        </div>
        <div className="grid min-w-0 flex-1 grid-cols-3 gap-2">
          {MAIN_ROWS.map((key) => {
            const player = data.players.find((p) => p.key === key);
            if (!player) return null;
            const bought = player.saldo_recente_rs > 0;
            const flat = player.saldo_recente_rs === 0;
            return (
              <div
                key={key}
                className="rounded-sm border border-zinc-800 bg-zinc-900/50 px-2 py-1.5"
              >
                <div className="flex items-center gap-1.5">
                  <span aria-hidden className="text-[11px] leading-none">
                    {MASCOT[key]}
                  </span>
                  <span
                    className={cn(
                      "text-[11px] font-bold uppercase tracking-wide",
                      LABEL_TONE[key],
                    )}
                  >
                    {player.label}
                  </span>
                </div>
                <div
                  className={cn(
                    "mt-0.5 text-[13px] font-bold tabular-nums",
                    flat ? "text-zinc-300" : bought ? "text-sky-400" : "text-red-400",
                  )}
                >
                  {money(player.saldo_recente_rs, currency)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <Aggressions items={data.aggressions} cut={cme ? CME_CUT : undefined} />

      <div className="mt-4">
        <PlayersFlowChart series={data.series} cme={cme} />
      </div>

      {!cme && (
      <details className="mt-3">
        <summary className="cursor-pointer text-[11px] text-zinc-300 hover:text-zinc-300">
          quem girou o dia (top 12 corretoras)
        </summary>
        <BrokerFilters
          grupo={grupo}
          lado={lado}
          ordem={ordem}
          onGrupo={setGrupo}
          onLado={setLado}
          onOrdem={setOrdem}
        />
        <table className="mt-2 w-full text-[11px]">
          <thead className="text-zinc-400">
            <tr>
              <SortHeader coluna="corretora" ordem={ordem} desc={desc} onSort={sortBy} />
              <SortHeader coluna="grupo" ordem={ordem} desc={desc} onSort={sortBy} />
              <SortHeader coluna="giro" ordem={ordem} desc={desc} onSort={sortBy} align="right" />
              <SortHeader coluna="saldo" ordem={ordem} desc={desc} onSort={sortBy} align="right" />
            </tr>
          </thead>
          <tbody className="text-zinc-400">
            {brokers.map((broker) => (
              <tr key={broker.code} className="border-t border-zinc-900">
                <td className="py-1">{broker.name}</td>
                <td className={cn("py-1", GROUP_TONE[broker.grupo] ?? "text-zinc-300")}>
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
            {brokers.length === 0 && (
              <tr>
                <td className="py-2 text-zinc-400" colSpan={4}>
                  nenhuma corretora nesse filtro.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </details>
      )}
    </section>
  );
}
