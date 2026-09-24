"use client";

import { useEffect, useRef, useState } from "react";
import { BASE_URL } from "@/lib/api";
import { PlayersTickList } from "@/lib/types";
import type { PlayersTick } from "@/lib/types";

/**
 * Preço e contagem de negócios, empurrados pelo backend.
 *
 * O collector entrega um negócio ~100ms depois de ele sair na B3. Perguntar de
 * novo a cada 100ms seria uma requisição por negócio; aqui o socket fica aberto
 * e o backend manda quando muda. Mesmo desenho do canal de fluxo do MT5.
 */
const WS_BASE = BASE_URL.replace(/^http/, "ws");
const RECONNECT_MS = 1_000;

export function usePlayersTick(path = "/api/players/ws/tick"): Record<string, PlayersTick> {
  const [ticks, setTicks] = useState<Record<string, PlayersTick>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let closed = false;
    let ws: WebSocket | null = null;

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(WS_BASE + path);
      ws.onmessage = (event) => {
        const parsed = PlayersTickList.safeParse(JSON.parse(event.data));
        if (parsed.success) {
          setTicks(Object.fromEntries(parsed.data.map((row) => [row.asset, row])));
        }
      };
      // Sem backoff: é a mesma máquina, e a carta parada é justamente o que
      // não pode acontecer — tentar de novo em 1s é o comportamento certo.
      ws.onclose = () => {
        ws = null;
        if (!closed) timer.current = setTimeout(connect, RECONNECT_MS);
      };
    };
    connect();

    return () => {
      closed = true;
      if (timer.current) clearTimeout(timer.current);
      ws?.close();
    };
  }, [path]);

  return ticks;
}
