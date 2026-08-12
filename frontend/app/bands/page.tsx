"use client";

import { Header } from "@/components/shared/Header";
import { BandProjectionChart } from "@/components/bands/BandProjectionChart";
import { useBandScenarios, useCandles } from "@/hooks/useCandles";
import { TRACKED_ASSETS } from "@/lib/types";

export default function BandsPage() {
  const candles = useCandles();
  const scenarios = useBandScenarios();

  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
        <p className="mb-4 text-xs text-zinc-500">
          Candles 5m (MT5) com Bollinger padrão (20, 2). A linha azul tracejada é
          o <span className="text-zinc-300">caminho típico do preço</span> daqui
          pra frente, e a faixa pontilhada em volta é a metade central do que
          aconteceu — medidos nas vezes anteriores em que o preço esteve nesse
          mesmo ponto da banda. É o histórico do próprio ativo, não previsão.
        </p>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {TRACKED_ASSETS.map(({ key, label }) => (
            <BandProjectionChart
              key={key}
              title={label}
              bars={candles?.[key] ?? []}
              scenario={scenarios?.[key]}
            />
          ))}
        </div>
      </main>
    </>
  );
}
