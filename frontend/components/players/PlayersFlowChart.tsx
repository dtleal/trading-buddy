"use client";

import type { PlayersBucket } from "@/lib/types";

const LINES = [
  { key: "baleia", label: "baleia", color: "#38bdf8" },
  { key: "banco", label: "banco", color: "#fbbf24" },
  { key: "sardinha", label: "sardinha", color: "#f87171" },
  { key: "rlp", label: "RLP (varejo B3)", color: "#4ade80" },
] as const;

const WIDTH = 720;
// Alto o bastante pra separar quatro linhas que andam juntas boa parte do dia.
const HEIGHT = 240;

/**
 * Cumulative net per group over the session, in reais, with price on the same
 * picture. Inline SVG on purpose: it is four polylines, and pulling a chart
 * library in for that would cost more than it gives. The point is the *shape*
 * — where a group turned around and whether price followed.
 */
export function PlayersFlowChart({ series }: { series: PlayersBucket[] }) {
  if (series.length < 2) {
    return (
      <p className="py-8 text-center text-xs text-zinc-400">
        aguardando fita suficiente pra desenhar
      </p>
    );
  }

  const cumulative = LINES.map(({ key, label, color }) => {
    let running = 0;
    const points = series.map((bucket) => (running += bucket[key]));
    return { key, label, color, points };
  });

  const flows = cumulative.flatMap((line) => line.points);
  const flowMax = Math.max(1, ...flows.map(Math.abs));
  const prices = series.map((bucket) => bucket.price).filter((price) => price > 0);
  const priceMin = Math.min(...prices);
  const priceMax = Math.max(...prices);
  const priceSpan = priceMax - priceMin || 1;

  const x = (index: number) => (index / (series.length - 1)) * WIDTH;
  const yFlow = (value: number) => HEIGHT / 2 - (value / flowMax) * (HEIGHT / 2 - 8);
  const yPrice = (value: number) =>
    HEIGHT - 8 - ((value - priceMin) / priceSpan) * (HEIGHT - 16);

  return (
    <div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-[240px] w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label="Saldo acumulado em reais por player ao longo do pregão"
      >
        <line
          x1={0}
          y1={HEIGHT / 2}
          x2={WIDTH}
          y2={HEIGHT / 2}
          stroke="#52525b"
          strokeWidth={1.5}
          strokeDasharray="4 4"
        />
        <polyline
          points={series
            .map((bucket, index) => `${x(index)},${yPrice(bucket.price)}`)
            .join(" ")}
          fill="none"
          stroke="#71717a"
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />
        {cumulative.map((line) => (
          <polyline
            key={line.key}
            points={line.points.map((value, index) => `${x(index)},${yFlow(value)}`).join(" ")}
            fill="none"
            stroke={line.color}
            strokeWidth={3}
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-zinc-300">
        <span className="text-zinc-400">saldo acumulado (R$)</span>
        {LINES.map((line) => (
          <span key={line.key} className="flex items-center gap-1">
            <span
              aria-hidden
              className="inline-block h-[3px] w-4 rounded-full"
              style={{ background: line.color }}
            />
            {line.label}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span aria-hidden className="inline-block h-[3px] w-4 rounded-full bg-zinc-500" />
          preço
        </span>
      </div>
    </div>
  );
}
