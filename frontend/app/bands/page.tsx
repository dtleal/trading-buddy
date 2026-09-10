"use client";

import { Header } from "@/components/shared/Header";
import { BandProjectionChart } from "@/components/bands/BandProjectionChart";
import { useBandScenarios, useCandles, useZones } from "@/hooks/useCandles";
import { useOrderFlow } from "@/hooks/useOrderFlow";
import { TRACKED_ASSETS } from "@/lib/types";

export default function BandsPage() {
  const candles = useCandles();
  const scenarios = useBandScenarios();
  // Regiões de compra/venda (toques repetidos que não romperam).
  const zones = useZones();
  // Live buy/sell pressure, same feed the Dashboard reads.
  const { flows } = useOrderFlow();

  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-[2100px] flex-1 px-4 py-6">
        <p className="mb-4 max-w-4xl text-xs text-zinc-500">
          Candles 5m (MT5) com Bollinger padrão (20, 2). As faixas{" "}
          <span className="text-red-400">vermelhas</span> e{" "}
          <span className="text-emerald-400">verdes</span> são as{" "}
          <span className="text-zinc-300">regiões</span>: preços onde o mercado
          virou 3 vezes ou mais e nunca fechou do outro lado, procurados no
          diário, no 15m e no 5m ao mesmo tempo. O selo na faixa diz quantos
          toques e em quais tempos — quanto mais forte, mais escura. Vermelha
          acima do preço = zona de venda, verde abaixo = zona de compra. O selo{" "}
          <span className="text-sky-400">% média</span> só aparece quando o
          preço está colado numa banda — é a chance de ele voltar pra média no
          estado de mercado atual (passe o mouse pros detalhes).
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {TRACKED_ASSETS.map(({ key, label }) => (
            <BandProjectionChart
              key={key}
              title={label}
              bars={candles?.[key] ?? []}
              scenario={scenarios?.[key]}
              flow={flows[key]}
              zones={zones?.[key]}
            />
          ))}
        </div>
      </main>
    </>
  );
}
