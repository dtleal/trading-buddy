"use client";

import { ConnectionStatusIndicator } from "@/components/shared/ConnectionStatusIndicator";
import type { ConnectionStatus } from "@/lib/ws";
import { Activity } from "lucide-react";

export function Header({
  status,
  lastTickAt,
}: {
  status: ConnectionStatus;
  lastTickAt: string | null;
}) {
  return (
    <header className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-3">
          <Activity className="size-5 text-sky-400" />
          <h1 className="text-base font-semibold tracking-tight text-zinc-100">
            trading-buddy
          </h1>
          <span className="text-xs text-zinc-500">USTEC · SPX · GOLD · VIX</span>
        </div>
        <div className="flex items-center gap-4">
          {lastTickAt && (
            <span className="text-xs text-zinc-500">
              último tick:{" "}
              <span className="text-zinc-300">
                {new Date(lastTickAt).toLocaleTimeString("pt-BR")}
              </span>
            </span>
          )}
          <ConnectionStatusIndicator status={status} />
        </div>
      </div>
    </header>
  );
}
