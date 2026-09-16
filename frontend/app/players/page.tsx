"use client";

import { Header } from "@/components/shared/Header";
import { AssetPlayersPanel } from "@/components/players/AssetPlayersPanel";
import { usePlayers } from "@/hooks/usePlayers";

export default function PlayersPage() {
  const { data, error } = usePlayers();

  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-[2100px] flex-1 px-4 py-6">
        <p className="mb-4 max-w-4xl text-xs text-zinc-500">
          Quem está do outro lado no <span className="text-zinc-300">WDO</span> e no{" "}
          <span className="text-zinc-300">WIN</span>, lido negócio a negócio do tape da
          B3 (Times &amp; Trades do Profit, que traz a corretora dos dois lados).{" "}
          <span className="text-emerald-400">B3 / RLP</span> é marcação dura: negócio RLP
          só existe pra cliente de varejo, então é sardinha por regra.{" "}
          <span className="text-zinc-300">leitura</span> é palpite nosso — agrupamos por
          corretora, e corretora não é o mesmo que tipo de investidor (a XP roteia
          institucional, o código do Itaú mistura mesa e cliente).
        </p>

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
            dois, e pra isso os dois têm que caber na mesma tela. Empilha
            de novo abaixo de lg, onde não cabe. */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {data?.assets.map((asset) => (
            <AssetPlayersPanel key={asset.asset} data={asset} />
          ))}
        </div>
      </main>
    </>
  );
}
