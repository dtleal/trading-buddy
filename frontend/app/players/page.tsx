"use client";

import { Header } from "@/components/shared/Header";
import { AssetPlayersPanel } from "@/components/players/AssetPlayersPanel";
import { IbovBreadth } from "@/components/players/IbovBreadth";
import { IbovTop10 } from "@/components/players/IbovTop10";
import { usePlayers } from "@/hooks/usePlayers";
import { usePlayersTick } from "@/hooks/usePlayersTick";
import { useIbov } from "@/hooks/useIbov";

export default function PlayersPage() {
  const { data, error } = usePlayers();
  const ibov = useIbov();
  const ticks = usePlayersTick();

  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-[2100px] flex-1 px-4 py-6">
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

        {/* Quem puxa à esquerda, quantos vieram junto à direita. */}
        {ibov && ibov.acoes.length > 0 && (
          <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_260px]">
            <IbovTop10 data={ibov} />
            <IbovBreadth data={ibov} />
          </div>
        )}

        {/* WDO e WIN lado a lado: o que interessa é a discordância entre os
            dois, e pra isso os dois têm que caber na mesma tela. Empilha
            de novo abaixo de lg, onde não cabe. */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data?.assets.map((asset) => (
            <AssetPlayersPanel key={asset.asset} data={asset} tick={ticks[asset.asset]} />
          ))}
        </div>
      </main>
    </>
  );
}
