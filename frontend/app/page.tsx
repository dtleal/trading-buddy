"use client";

import { Header } from "@/components/shared/Header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useLiveTick } from "@/hooks/useLiveTick";
import { fmtPrice, fmtPct } from "@/lib/utils";

export default function Home() {
  const { tick, status } = useLiveTick();

  return (
    <>
      <Header status={status} lastTickAt={tick?.timestamp ?? null} />

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-6 space-y-6">
        {/* TODO Phase 3: VixChart and VixAlertsPanel land here */}

        <Card>
          <CardHeader>
            <CardTitle>VIX</CardTitle>
            <CardDescription>
              Gráfico e alertas chegam na Fase 3 — por enquanto leitura ao vivo
              via WebSocket abaixo.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {tick ? (
              <div className="space-y-2">
                <div className="flex items-baseline gap-3 text-3xl font-semibold tabular-nums">
                  {fmtPrice(tick.market.vix.vix)}
                </div>
                <div className="flex flex-wrap gap-2 text-xs">
                  <Badge tone={regimeTone(tick.market.vix.regime)}>
                    regime: {tick.market.vix.regime}
                  </Badge>
                  <Badge tone={termTone(tick.market.vix.term_structure)}>
                    term: {tick.market.vix.term_structure}
                  </Badge>
                  {tick.market.vix.vix9d !== null && (
                    <Badge>VIX9D: {fmtPrice(tick.market.vix.vix9d)}</Badge>
                  )}
                  {tick.market.vix.vix3m !== null && (
                    <Badge>VIX3M: {fmtPrice(tick.market.vix.vix3m)}</Badge>
                  )}
                </div>
              </div>
            ) : (
              <p className="text-sm text-zinc-500">Aguardando primeiro tick…</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Ativos</CardTitle>
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
