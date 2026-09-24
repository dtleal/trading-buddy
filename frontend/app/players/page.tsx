"use client";

import { Header } from "@/components/shared/Header";
import { AggressionAlert } from "@/components/players/AggressionAlert";
import { AgendaPanel } from "@/components/agenda/AgendaPanel";
import { AssetPlayersPanel } from "@/components/players/AssetPlayersPanel";
import { IbovBreadth } from "@/components/players/IbovBreadth";
import { IbovTop10 } from "@/components/players/IbovTop10";
import { usePlayers } from "@/hooks/usePlayers";
import { usePlayersTick } from "@/hooks/usePlayersTick";
import { useIbov } from "@/hooks/useIbov";
import { useAggressionAlert } from "@/hooks/useAggressionAlert";

export default function PlayersPage() {
  const { data, error } = usePlayers();
  const ibov = useIbov();
  const ticks = usePlayersTick();
  const { alert, dismiss } = useAggressionAlert(data);

  return (
    <>
      {alert && <AggressionAlert alert={alert} onDismiss={dismiss} />}
      <Header />
      <main className="mx-auto w-full max-w-[2100px] flex-1 px-4 py-3">
        {error && (
          <p className="mb-4 rounded border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
            backend fora do ar ou sem resposta.
          </p>
        )}

        {data && data.source === "" && (
          <p className="mb-4 rounded border border-amber-900 bg-amber-950/30 p-3 text-xs text-amber-300">
            Sem fonte: <code>PROFIT_DATA_DIR</code> não está apontando pra pasta do
            Nelogica Profit. Confira <code>PROFIT_DIR_HOST</code> no <code>.env</code>.
          </p>
        )}

        {data?.loading && data.assets.length > 0 && (
          <p className="mb-4 rounded border border-sky-900 bg-sky-950/30 p-3 text-xs text-sky-300">
            Lendo o tape do pregão — os números são o dia até aqui e vão crescer
            nos próximos segundos.
          </p>
        )}

        {data && data.source !== "" && data.assets.length === 0 && (
          <p className="mb-4 rounded border border-amber-900 bg-amber-950/30 p-3 text-xs text-amber-300">
            Pasta do Profit encontrada, mas sem arquivo de tape. Abra o Profit com
            Times &amp; Trades do WDO e do WIN pra ele começar a gravar.
          </p>
        )}

        {/* WDO e WIN lado a lado: o que interessa é a discordância entre os
            dois, e pra isso os dois têm que caber na mesma tela. As ações e a
            agenda vão numa coluna fina à direita, pra tudo caber sem rolar.
            Empilha de novo abaixo de xl, onde não cabe. */}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1fr_280px]">
          {data?.assets.map((asset) => (
            <AssetPlayersPanel key={asset.asset} data={asset} tick={ticks[asset.asset]} />
          ))}
          <aside className="space-y-4">
            {ibov && ibov.acoes.length > 0 && (
              <>
                <IbovTop10 data={ibov} />
                <IbovBreadth data={ibov} />
              </>
            )}
            <AgendaPanel compact />
          </aside>
        </div>
      </main>
    </>
  );
}
