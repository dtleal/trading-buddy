"use client";

import { ExternalLink } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { DashboardTick, NewsItem } from "@/lib/types";
import { cn } from "@/lib/utils";

const MAX = 12;

/** Headlines from the news sources (RSS + NewsAPI). Mirrors the CLI panel. */
export function NewsPanel({ tick }: { tick: DashboardTick | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Manchetes recentes</CardTitle>
        <CardDescription>
          RSS de Reuters/CNBC/MarketWatch + NewsAPI quando a chave está configurada
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!tick ? (
          <p className="text-sm text-zinc-500">Aguardando primeiro tick…</p>
        ) : tick.recent_news.length === 0 ? (
          <p className="text-sm italic text-zinc-500">Sem manchetes recentes.</p>
        ) : (
          <ul className="space-y-2">
            {tick.recent_news.slice(0, MAX).map((item, i) => (
              <NewsRow key={`${item.url || item.headline}-${i}`} item={item} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function NewsRow({ item }: { item: NewsItem }) {
  const sentTone = sentimentTone(item.sentiment_label);
  return (
    <li className="flex flex-col gap-1 border-l-2 border-zinc-800 pl-3">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500">
        <span>{item.source}</span>
        {item.sentiment_label && (
          <Badge tone={sentTone}>{item.sentiment_label}</Badge>
        )}
        <span className="ml-auto tabular-nums">{relativeTime(item.published_at)}</span>
      </div>
      {item.url ? (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "inline-flex items-start gap-1 text-sm text-zinc-200 hover:text-sky-300",
          )}
        >
          <span>{item.headline}</span>
          <ExternalLink className="mt-0.5 size-3 shrink-0 text-zinc-500" />
        </a>
      ) : (
        <span className="text-sm text-zinc-200">{item.headline}</span>
      )}
    </li>
  );
}

function sentimentTone(label: NewsItem["sentiment_label"]) {
  if (label === "positive") return "positive";
  if (label === "negative") return "negative";
  return "neutral";
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMin = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (diffMin < 1) return "agora";
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  return `${Math.round(diffH / 24)}d`;
}
