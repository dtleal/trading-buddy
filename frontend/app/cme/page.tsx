"use client";

import { Header } from "@/components/shared/Header";
import { AggressionAlert } from "@/components/players/AggressionAlert";
import { AssetPlayersPanel } from "@/components/players/AssetPlayersPanel";
import { usePlayers } from "@/hooks/usePlayers";
import { usePlayersTick } from "@/hooks/usePlayersTick";
import { useAggressionAlert } from "@/hooks/useAggressionAlert";
import { api } from "@/lib/api";

/**
 * A aba B3 para a CME: ouro (GC), Nasdaq (NQ) e S&P (ES), com os micros
 * somados como 1/10 do mini. A fita da CME é anônima, então baleia / banco /
 * sardinha aqui é o tamanho do lote, não a corretora.
 */
export default function CmePage() {
  const { data, error } = usePlayers(api.getCme);
  const ticks = usePlayersTick("/api/cme/ws/tick");
  const { alert, dismiss } = useAggressionAlert(data);

  return (
    <>
      {alert && <AggressionAlert alert={alert} onDismiss={dismiss} />}
      <Header />
      <main className="mx-auto w-full max-w-[2100px] flex-1 px-4 py-6">
        {error && (
          <p className="mb-4 rounded border border-red-900 bg-red-950/40 p-3 text-xs text-red-300">
            backend fora do ar ou sem resposta.
          </p>
        )}

        {data && data.assets.length === 0 && (
          <p className="mb-4 rounded border border-amber-900 bg-amber-950/30 p-3 text-xs text-amber-300">
            Sem fita da CME ainda. Precisa do plugin Sinal CME Level 2 da Nelogica. No
            Profit, abra o Times &amp; Trades do GC, NQ e ES (ou dos micros MGC, MNQ,
            MES) e linke cada janela com &quot;Linkar Janela com Excel (RTD)&quot;.
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {data?.assets.map((asset) => (
            <AssetPlayersPanel key={asset.asset} data={asset} tick={ticks[asset.asset]} cme />
          ))}
        </div>
      </main>
    </>
  );
}
