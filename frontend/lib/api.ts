/**
 * HTTP client. Validates every response against the Zod schemas in `types.ts`.
 */
import { DashboardTick, VixHistoryResponse } from "@/lib/types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
