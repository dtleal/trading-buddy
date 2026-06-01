"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ConnectionStatusIndicator } from "@/components/shared/ConnectionStatusIndicator";
import type { ConnectionStatus } from "@/lib/ws";
import { cn } from "@/lib/utils";
import { Activity } from "lucide-react";

const TABS = [
  { href: "/", label: "Dashboard" },
  { href: "/qa", label: "Q&A" },
] as const;

/**
 * App header with tab navigation between the live Dashboard and the Q&A
 * knowledge base. `status`/`lastTickAt` are only passed on the Dashboard
 * (which owns the live WebSocket tick); the connection indicator is hidden
 * elsewhere.
 */
export function Header({
  status,
  lastTickAt,
}: {
  status?: ConnectionStatus;
  lastTickAt?: string | null;
}) {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <Activity className="size-5 text-sky-400" />
            <h1 className="text-base font-semibold tracking-tight text-zinc-100">
              trading-buddy
            </h1>
          </div>
          <nav className="flex items-center gap-1">
            {TABS.map((tab) => {
              const active = pathname === tab.href;
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    active
                      ? "bg-zinc-800 text-zinc-100"
                      : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200",
                  )}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>
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
          {status && <ConnectionStatusIndicator status={status} />}
        </div>
      </div>
    </header>
  );
}
