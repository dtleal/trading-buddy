"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { shout } from "@/lib/alerts/sound";
import type { AgendaEvent, AgendaResponse } from "@/lib/types";

/** The backend caches the agenda for 3 min, so a faster poll only re-reads it. */
const POLL_MS = 60_000;
/** How often the clock is checked against the event times. */
const CHECK_MS = 10_000;
/** Minutes before each event when the alert goes off. */
const STAGES = [30, 15, 5] as const;
const HOLD_MS = 30_000;

export type AgendaAlert = { event: AgendaEvent; minutes: number };

/** Polls /api/agenda. Keeps the last good answer when a poll fails. */
export function useAgenda(): AgendaResponse | null {
  const [data, setData] = useState<AgendaResponse | null>(null);

  const refresh = useCallback(async () => {
    try {
      setData(await api.getAgenda());
    } catch {
      /* stay on the last agenda */
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  return data;
}

/**
 * Siren + voice at 30, 15 and 5 minutes before each event.
 *
 * Each stage goes off once. If the page opens late (say 20 min before), only
 * the stage just passed goes off, with the real minutes left, and the ones
 * behind it are marked done — no burst of three alerts at once.
 */
export function useAgendaAlert(data: AgendaResponse | null): {
  alert: AgendaAlert | null;
  dismiss: () => void;
} {
  const fired = useRef(new Set<string>());
  const [alert, setAlert] = useState<AgendaAlert | null>(null);

  useEffect(() => {
    if (!data) return;
    const check = () => {
      const now = Date.now();
      for (const event of data.eventos) {
        const left = (new Date(event.at).getTime() - now) / 60_000;
        if (left <= 0) continue;
        const crossed = STAGES.filter((stage) => left <= stage);
        const stage = crossed[crossed.length - 1];
        if (stage === undefined) continue;
        const key = (s: number) => `${event.at}|${event.title}|${s}`;
        if (fired.current.has(key(stage))) continue;
        for (const s of crossed) fired.current.add(key(s));
        const minutes = Math.ceil(left);
        setAlert({ event, minutes });
        // TradingView titles are always in English, so read them in English.
        if (event.source === "TradingView") {
          shout(`News in ${minutes} minutes: ${event.title}`, "en-US");
        } else {
          shout(`Notícia em ${minutes} minutos: ${event.title}`);
        }
      }
    };
    check();
    const id = setInterval(check, CHECK_MS);
    return () => clearInterval(id);
  }, [data]);

  useEffect(() => {
    if (!alert) return;
    const id = setTimeout(() => setAlert(null), HOLD_MS);
    return () => clearTimeout(id);
  }, [alert]);

  return { alert, dismiss: () => setAlert(null) };
}
