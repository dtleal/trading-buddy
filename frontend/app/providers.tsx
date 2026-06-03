"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { installAudioUnlock } from "@/lib/alerts/sound";

export function Providers({ children }: { children: ReactNode }) {
  // Browsers gate Web Audio behind a user gesture. Arm one-time listeners so
  // the alert chime is ready after the first click/keypress anywhere.
  useEffect(() => installAudioUnlock(), []);

  // One QueryClient per app instance. Created in state so Strict Mode's
  // double-effect doesn't tear it down.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, err) => {
              // Don't retry on 503 — backend just warming up; the WS will
              // catch up. Other errors get 2 retries.
              const status = (err as { status?: number }).status;
              if (status === 503) return false;
              return failureCount < 2;
            },
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster richColors position="top-right" theme="dark" closeButton />
    </QueryClientProvider>
  );
}
