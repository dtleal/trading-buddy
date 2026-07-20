"use client";

import { Header } from "@/components/shared/Header";
import { VixChart } from "@/components/vix/VixChart";
import { VixAlertsPanel } from "@/components/vix/VixAlertsPanel";
import { PricesPanel } from "@/components/market/PricesPanel";
import { IntradayLevelsPanel } from "@/components/market/IntradayLevelsPanel";
import { BiasPanel } from "@/components/bias/BiasPanel";
import { SetupsPanel } from "@/components/setups/SetupsPanel";
import { EventsPanel } from "@/components/events/EventsPanel";
import { NewsPanel } from "@/components/news/NewsPanel";
import { BreakoutsPanel } from "@/components/breakouts/BreakoutsPanel";
import { DayOutlookBanner } from "@/components/dayoutlook/DayOutlookBanner";
import { OrderFlowSection } from "@/components/orderflow/OrderFlowSection";
import { PnlCards } from "@/components/orderflow/PnlCards";
import { BriefingPanel } from "@/components/briefing/BriefingPanel";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useLiveTick } from "@/hooks/useLiveTick";
import { useVixAlerts } from "@/hooks/useVixAlerts";
import { useBreakoutAlerts } from "@/hooks/useBreakoutAlerts";
import { fmtPrice } from "@/lib/utils";

export default function Home() {
  const { tick, status } = useLiveTick();
  const vix = tick?.market.vix.vix ?? null;
  useVixAlerts(tick);
  useBreakoutAlerts(tick);

  return (
    <>
      <Header status={status} lastTickAt={tick?.timestamp ?? null} />

      <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-6 space-y-6">
        {/* Resultado realizado — dia / semana / mês, no topo da tela */}
        <PnlCards />

        {/* Perfil do Dia — movement-potential / liquidity gate, top of the fold */}
        <DayOutlookBanner tick={tick} />

        {/* Row 0: VIX chart on its own (pressure now lives per-column in the flow) */}
        <Card>
            <CardHeader>
              <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <CardTitle>VIX</CardTitle>
                  <CardDescription>
                    5m intraday · linhas verde (calmo, 15) e vermelha (stress, 25)
                  </CardDescription>
                </div>
                {tick && (
                  <div className="flex items-baseline gap-3">
                    <span className="text-3xl font-semibold tabular-nums text-zinc-100">
                      {fmtPrice(tick.market.vix.vix)}
                    </span>
                    <div className="flex flex-wrap gap-2">
                      <Badge tone={regimeTone(tick.market.vix.regime)}>
                        {tick.market.vix.regime}
                      </Badge>
                      <Badge tone={termTone(tick.market.vix.term_structure)}>
                        {tick.market.vix.term_structure}
                      </Badge>
                    </div>
                  </div>
                )}
              </div>
            </CardHeader>
          <CardContent>
            <VixChart liveVix={vix} height={200} />
          </CardContent>
        </Card>

        {/* Row 0b: live order flow — each column carries its pressure marker on top */}
        <OrderFlowSection tick={tick} />

        {/* Briefing panel — collapsed by default, full-width */}
        <BriefingPanel />

        {/* VIX alerts (moved out of the hero row) */}
        <VixAlertsPanel />

        {/* Row 2: prices (cards inside) + 5m reference levels */}
        <PricesPanel tick={tick} />
        <IntradayLevelsPanel tick={tick} />

        {/* Row 3: bias + setups side by side on desktop */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <BiasPanel tick={tick} />
          <SetupsPanel tick={tick} />
        </div>

        {/* Row 4: breakouts (full width — most relevant for day trading) */}
        <BreakoutsPanel tick={tick} />

        {/* Row 5: calendar + news side by side */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <EventsPanel tick={tick} />
          <NewsPanel tick={tick} />
        </div>
      </main>
    </>
  );
}

function regimeTone(r: string): "positive" | "warning" | "negative" {
  if (r === "low") return "positive";
  if (r === "high") return "negative";
  return "warning";
}

function termTone(t: string): "positive" | "warning" | "negative" {
  if (t === "contango") return "positive";
  if (t === "backwardation") return "negative";
  return "warning";
}
