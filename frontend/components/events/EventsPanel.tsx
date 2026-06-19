"use client";

import { Check } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DashboardTick, EconomicEvent, ImpactLevel } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Economic calendar. Mirrors the CLI's "Eventos de hoje" table including the
 * past-event marker ("✓ ENCERRADO") with strike-through + dim styling.
 */
export function EventsPanel({ tick }: { tick: DashboardTick | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Eventos de hoje</CardTitle>
        <CardDescription>
          Calendário US (medium / high impact). Horário em UTC e BRT.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!tick ? (
          <p className="text-sm text-zinc-500">Aguardando primeiro tick…</p>
        ) : tick.events_today.length === 0 ? (
          <p className="text-sm italic text-zinc-500">
            Sem eventos relevantes hoje (ou ForexFactory rate-limitando).
          </p>
        ) : (
          <ul className="space-y-1.5">
            {tick.events_today.map((e, i) => (
              <EventRow key={`${e.name}-${i}`} event={e} now={Date.now()} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function EventRow({ event, now }: { event: EconomicEvent; now: number }) {
  const scheduled = new Date(event.scheduled_at).getTime();
  const past = scheduled < now;

  const utc = new Date(event.scheduled_at).toLocaleTimeString("pt-BR", {
    timeZone: "UTC",
    hour: "2-digit",
    minute: "2-digit",
  });
  const brt = new Date(event.scheduled_at).toLocaleTimeString("pt-BR", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <li
      className={cn(
        "grid grid-cols-[auto_auto_auto_1fr_auto] items-center gap-3 rounded border border-zinc-800 bg-zinc-900/30 px-3 py-2 text-sm",
        past && "opacity-60",
      )}
    >
      <span className={cn("tabular-nums text-zinc-400", past && "line-through")}>{utc} UTC</span>
      <span className={cn("tabular-nums text-zinc-400", past && "line-through")}>{brt} BRT</span>
      {past ? (
        <Badge tone="neutral">
          <Check className="mr-1 size-3" />
          ENCERRADO{event.actual ? ` → ${event.actual}` : ""}
        </Badge>
      ) : (
        <ImpactBadge impact={event.impact} />
      )}
      <span className={cn("text-zinc-200", past && "line-through")}>{event.name}</span>
      <span className="text-xs tabular-nums text-zinc-500">
        {event.forecast ?? "—"} / {event.previous ?? "—"}
      </span>
    </li>
  );
}

function ImpactBadge({ impact }: { impact: ImpactLevel }) {
  if (impact === "high") return <Badge tone="negative">HIGH</Badge>;
  if (impact === "medium") return <Badge tone="warning">MEDIUM</Badge>;
  if (impact === "holiday") return <Badge tone="warning">FERIADO</Badge>;
  return <Badge tone="neutral">LOW</Badge>;
}
