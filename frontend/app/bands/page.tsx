"use client";

import { Header } from "@/components/shared/Header";
import { BandProjectionChart } from "@/components/bands/BandProjectionChart";
import { useCandles } from "@/hooks/useCandles";
import { TRACKED_ASSETS } from "@/lib/types";

export default function BandsPage() {
  const candles = useCandles();

  return (
    <>
      <Header />
      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6">
        <p className="mb-4 text-xs text-zinc-500">
          Candles 5m (MT5) com Bollinger padrão (20, 2). O tracejado é a
          continuação projetada das bandas nos próximos 30 min, assumindo que o
          preço segue a inclinação recente — é extrapolação, não previsão.
        </p>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {TRACKED_ASSETS.map(({ key, label }) => (
            <BandProjectionChart key={key} title={label} bars={candles?.[key] ?? []} />
          ))}
        </div>
      </main>
    </>
  );
}
