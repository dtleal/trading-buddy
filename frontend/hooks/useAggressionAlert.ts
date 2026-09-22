"use client";

import { useEffect, useRef, useState } from "react";
import type { PlayersAggression, PlayersResponse } from "@/lib/types";

/** Quanto tempo o aviso fica na tela antes de sumir sozinho. */
const HOLD_MS = 20_000;

export type AggressionAlert = PlayersAggression & { asset: string };

/** A janela aberta é a identidade da agressão: `at` é o primeiro negócio dela,
 *  então ela continua sendo a mesma linha enquanto os contratos crescem. */
function keyOf(asset: string, item: PlayersAggression): string {
  return `${asset}|${item.at}|${item.agressor}|${item.lado}`;
}

/**
 * Avisa quando aparece uma agressão que ainda não tinha aparecido.
 *
 * A primeira resposta do backend traz o pregão inteiro até aqui, e nada disso
 * é novidade — seria um alerta gigante na cara por causa de algo que aconteceu
 * de manhã. Por isso a primeira leitura só carimba o que já existe e não
 * dispara nada.
 */
export function useAggressionAlert(data: PlayersResponse | null): {
  alert: AggressionAlert | null;
  dismiss: () => void;
} {
  const seen = useRef<Set<string> | null>(null);
  const [alert, setAlert] = useState<AggressionAlert | null>(null);

  useEffect(() => {
    if (!data) return;
    const current = data.assets.flatMap((asset) =>
      asset.aggressions.map((item) => ({ ...item, asset: asset.asset })),
    );
    if (seen.current === null) {
      seen.current = new Set(current.map((item) => keyOf(item.asset, item)));
      return;
    }
    const fresh = current.filter((item) => !seen.current!.has(keyOf(item.asset, item)));
    for (const item of fresh) seen.current.add(keyOf(item.asset, item));
    // Se caírem duas juntas, a mais nova é a que fica na tela.
    const newest = fresh.sort((a, b) => b.at.localeCompare(a.at))[0];
    if (newest) setAlert(newest);
  }, [data]);

  useEffect(() => {
    if (!alert) return;
    const id = setTimeout(() => setAlert(null), HOLD_MS);
    return () => clearTimeout(id);
  }, [alert]);

  return { alert, dismiss: () => setAlert(null) };
}
