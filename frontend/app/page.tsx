"use client";

import { Header } from "@/components/shared/Header";
import { VixChart } from "@/components/vix/VixChart";
import { VixAlertsPanel } from "@/components/vix/VixAlertsPanel";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useLiveTick } from "@/hooks/useLiveTick";
import { useVixAlerts } from "@/hooks/useVixAlerts";
import { fmtPrice, fmtPct } from "@/lib/utils";

export default function Home() {
  const { tick, status } = useLiveTick();
  const vix = tick?.market.vix.vix ?? null;
  useVixAlerts(tick);

  return (
    <>
      <Header status={status} lastTickAt={tick?.timestamp ?? null} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6 space-y-6">
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle>VIX</CardTitle>
                <CardDescription>
                  5m intraday · linhas verdes (calmo, 15) e vermelha (stress, 25)
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
            <VixChart liveVix={vix} />
          </CardContent>
        </Card>

        <VixAlertsPanel />

        <Card>
          <CardHeader>
            <CardTitle>Ativos</CardTitle>
            <CardDescription>USTEC · SPX · GOLD — leitura ao vivo</CardDescription>
          </CardHeader>
          <CardContent>
            {tick ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {Object.entries(tick.market.assets).map(([sym, q]) => (
                  <div
                    key={sym}
                    className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3"
                  >
                    <div className="text-xs uppercase tracking-wider text-zinc-500">
                      {sym}
                    </div>
                    <div className="mt-1 text-2xl font-semibold tabular-nums">
                      {fmtPrice(q.price)}
                    </div>
                    <div
                      className={`text-xs tabular-nums ${
                        (q.change_pct ?? 0) >= 0
                          ? "text-emerald-400"
                          : "text-red-400"
                      }`}
                    >
                      {fmtPct(q.change_pct)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-zinc-500">Aguardando primeiro tick…</p>
            )}
          </CardContent>
        </Card>
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
