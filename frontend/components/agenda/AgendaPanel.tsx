"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAgenda } from "@/hooks/useAgenda";
import { cn } from "@/lib/utils";

function hhmm(at: string): string {
  return new Date(at).toLocaleTimeString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Agenda do dia (BR + EUA) e as últimas manchetes, pra WIN, WDO e GOLD.
 *  `compact` = só a agenda, numa coluna e letra menor (a coluna lateral da aba B3). */
export function AgendaPanel({ compact = false }: { compact?: boolean }) {
  const data = useAgenda();
  const now = Date.now();

  return (
    <Card>
      <CardHeader className={cn(compact && "p-3 pb-1")}>
        <CardTitle>{compact ? "Agenda" : "Agenda e notícias"}</CardTitle>
        {!compact && (
          <CardDescription>
            TradingView + agenda do presidente do BC + Valor/InfoMoney. Alerta 30, 15 e 5 min
            antes.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent
        className={cn("grid grid-cols-1 gap-4", compact ? "p-3 pt-0" : "lg:grid-cols-2")}
      >
        <ul className="space-y-1">
          {!data ? (
            <li className="text-sm text-zinc-500">Carregando…</li>
          ) : data.eventos.length === 0 ? (
            <li className="text-sm italic text-zinc-500">Sem eventos hoje.</li>
          ) : (
            data.eventos.map((e) => (
              <li
                key={`${e.at}-${e.title}`}
                title={e.title}
                className={cn(
                  "flex items-baseline gap-2",
                  compact ? "text-[11px]" : "text-sm",
                  new Date(e.at).getTime() < now && "opacity-50 line-through",
                )}
              >
                <span className="tabular-nums text-zinc-400">{hhmm(e.at)}</span>
                <span className="w-5 shrink-0 text-xs font-bold text-zinc-500">{e.country}</span>
                <span
                  className={cn(
                    "text-zinc-200",
                    compact && "min-w-0 truncate",
                    e.importance >= 1 && "font-bold text-amber-300",
                  )}
                >
                  {e.title}
                </span>
                {e.actual && <span className="text-xs text-zinc-400">→ {e.actual}</span>}
              </li>
            ))
          )}
        </ul>
        {!compact && (
          <ul className="space-y-1">
            {data?.manchetes.map((h) => (
              <li key={h.url} className="text-sm">
                <span className="tabular-nums text-zinc-500">{hhmm(h.at)} </span>
                <a
                  href={h.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-zinc-200 hover:underline"
                >
                  {h.title}
                </a>
                <span className="text-xs text-zinc-500"> · {h.source}</span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
