"use client";

import { cn } from "@/lib/utils";
import type { PlayersAggression } from "@/lib/types";

/**
 * Agressões: uma baleia ou um banco martelando o mesmo lado numa janela de 2
 * minutos.
 *
 * É assim que ordem grande de verdade aparece. A B3 fatia — o maior negócio
 * único medido foi 1.465 contratos no WIN e 2.232 no WDO — então "a baleia
 * mandou 10 mil" nunca é uma linha na fita, são centenas de linhas seguidas do
 * mesmo agressor.
 *
 * Varejo fica de fora: a XP agredindo 30.000 contratos é a soma dos clientes
 * dela (18.574 negócios de ~2,9 contratos), não um player. Os cortes e o
 * filtro moram no backend, em AGGRESSION_CONTRACTS.
 */
const SHOW = 10;

const GROUP_TONE: Record<string, string> = {
  baleia: "text-sky-400",
  banco: "text-amber-400",
  sardinha: "text-zinc-400",
};

export function Aggressions({ items }: { items: PlayersAggression[] }) {
  return (
    <div className="mt-3 rounded-sm border border-zinc-800 bg-zinc-900/40 px-2 py-1.5">
      <span
        className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400"
        title="Mesmo agressor, mesmo lado, dentro de 2 minutos. Corte: 25.000 contratos no WIN, 4.000 no WDO."
      >
        agressões · 2 min
      </span>

      {items.length === 0 ? (
        <p className="py-1 text-[11px] text-zinc-500">
          nenhuma agressão no pregão até aqui.
        </p>
      ) : (
        <table className="mt-1 w-full text-[11px]">
          {/* Sem título de coluna a contagem de negócios virava um "8.730n" que
              ninguém sabia ler. */}
          <thead className="text-zinc-500">
            <tr>
              <th className="py-0.5 text-left font-normal">hora</th>
              <th className="py-0.5 text-left font-normal">contratos</th>
              <th className="py-0.5 text-right font-normal">negócios</th>
              <th className="py-0.5 pl-2 text-left font-normal">agressor</th>
              <th className="py-0.5 pl-2 text-right font-normal">preço ini</th>
              <th className="py-0.5 text-right font-normal">preço méd</th>
              <th className="py-0.5 text-right font-normal">preço fim</th>
              <th className="py-0.5 text-right font-normal">var</th>
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {items.slice(0, SHOW).map((item) => {
              const bought = item.lado === "COMPRA";
              const move = item.price_to - item.price_from;
              return (
                <tr key={`${item.at}-${item.agressor}-${item.lado}`} className="border-t border-zinc-900">
                  <td className="py-0.5 text-zinc-500">{item.at.slice(11, 16)}</td>
                  <td className={cn("py-0.5 font-bold", bought ? "text-sky-400" : "text-red-400")}>
                    {bought ? "▲" : "▼"} {item.qty.toLocaleString("pt-BR")}
                  </td>
                  {/* Quantos negócios pra chegar lá: separa mesa de corretora. */}
                  <td className="py-0.5 text-right text-zinc-500">
                    {item.trades.toLocaleString("pt-BR")}
                  </td>
                  <td className={cn("truncate py-0.5 pl-2 font-semibold", GROUP_TONE[item.grupo])}>
                    {item.agressor}
                  </td>
                  {/* Onde a agressão começou e onde parou. O passo do WIN é 5
                      pontos e o do WDO é 0,5, então os dois cabem sem casa
                      decimal forçada. */}
                  <td className="py-0.5 pl-2 text-right text-zinc-400">
                    {item.price_from.toLocaleString("pt-BR")}
                  </td>
                  {/* Ponderado por contrato: é o preço que a mesa realmente
                      pagou, e o nível que ela vai defender. */}
                  <td className="py-0.5 text-right text-zinc-400">
                    {item.price_avg.toLocaleString("pt-BR")}
                  </td>
                  <td className="py-0.5 text-right text-zinc-300">
                    {item.price_to.toLocaleString("pt-BR")}
                  </td>
                  {/* Pra onde o preço foi enquanto isso: é a pergunta toda. */}
                  <td
                    className={cn(
                      "py-0.5 text-right",
                      move > 0 ? "text-sky-400" : move < 0 ? "text-red-400" : "text-zinc-500",
                    )}
                  >
                    {move > 0 ? "+" : ""}
                    {move.toLocaleString("pt-BR")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
