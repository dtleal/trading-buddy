"use client";

import { cn } from "@/lib/utils";
import type { ConnectionStatus } from "@/lib/ws";

const LABEL: Record<ConnectionStatus, string> = {
  connecting: "conectando…",
  open: "ao vivo",
  reconnecting: "reconectando…",
  closed: "offline",
};

const DOT: Record<ConnectionStatus, string> = {
  connecting: "bg-amber-400 animate-pulse",
  open: "bg-emerald-400",
  reconnecting: "bg-amber-400 animate-pulse",
  closed: "bg-zinc-500",
};

export function ConnectionStatusIndicator({ status }: { status: ConnectionStatus }) {
  return (
    <div className="flex items-center gap-2 text-xs text-zinc-400">
      <span className={cn("inline-block size-2 rounded-full", DOT[status])} />
      <span>{LABEL[status]}</span>
    </div>
  );
}
