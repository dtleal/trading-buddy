/**
 * HTTP client. Validates every response against the Zod schemas in `types.ts`.
 */
import { DashboardTick, VixHistoryResponse } from "@/lib/types";

/**
 * API base URL resolution:
 * 1. Build-time `NEXT_PUBLIC_API_URL` always wins (for production deploys
 *    with a known backend host).
 * 2. In the browser, derive from `window.location` so the same bundle works
 *    whether you load the app at http://localhost:3000, http://<lan-ip>:3000,
 *    http://machine.local:3000, etc. The phone hitting the LAN IP gets the
 *    LAN IP back instead of the broken "localhost".
 * 3. Server-side fallback (SSR / build): localhost.
 */
function resolveBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL && process.env.NEXT_PUBLIC_API_URL.length > 0) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://localhost:8000";
}

const BASE_URL = resolveBaseUrl();

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchJson<T>(path: string, schema: { parse: (v: unknown) => T }): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new ApiError(res.status, `${path}: HTTP ${res.status} — ${detail}`);
  }
  const json = await res.json();
  return schema.parse(json);
}

export const api = {
  getTick: () => fetchJson("/api/tick", DashboardTick),
  getVixHistory: (lookbackDays = 2, interval = "5m") =>
    fetchJson(
      `/api/vix/history?lookback_days=${lookbackDays}&interval=${interval}`,
      VixHistoryResponse,
    ),
};

export { ApiError, BASE_URL };
