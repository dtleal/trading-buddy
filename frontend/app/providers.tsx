"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";

export function Providers({ children }: { children: ReactNode }) {
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
