/**
 * WebSocket client with auto-reconnect and Zod-validated messages.
 *
 * Used by `hooks/useLiveTick` to subscribe to /ws/ticks. The connection
 * indicator in the layout reads the same `ConnectionStatus` exposed here.
 */
import { DashboardTick } from "@/lib/types";
import { BASE_URL } from "@/lib/api";

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

type Listener = (tick: DashboardTick) => void;
type StatusListener = (status: ConnectionStatus) => void;

const WS_URL = BASE_URL.replace(/^http/, "ws") + "/ws/ticks";
const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 30_000;

export class TickClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private statusListeners = new Set<StatusListener>();
  private backoff = INITIAL_BACKOFF_MS;
  private closed = false;
  private status: ConnectionStatus = "connecting";

  start(): void {
    this.closed = false;
    this.connect();
  }

  stop(): void {
    this.closed = true;
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setStatus("closed");
  }

  onTick(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: StatusListener): () => void {
    this.statusListeners.add(fn);
    fn(this.status); // emit current status immediately
    return () => this.statusListeners.delete(fn);
  }

  private setStatus(s: ConnectionStatus): void {
    this.status = s;
    this.statusListeners.forEach((fn) => fn(s));
  }

  private connect(): void {
    if (this.closed) return;
    this.setStatus(this.backoff === INITIAL_BACKOFF_MS ? "connecting" : "reconnecting");

    const ws = new WebSocket(WS_URL);
    this.ws = ws;

    ws.onopen = () => {
      this.backoff = INITIAL_BACKOFF_MS;
      this.setStatus("open");
    };

    ws.onmessage = (event) => {
      try {
        const raw = JSON.parse(event.data);
        const parsed = DashboardTick.safeParse(raw);
        if (!parsed.success) {
          console.warn("WS: tick failed validation", parsed.error.flatten());
          return;
        }
        this.listeners.forEach((fn) => fn(parsed.data));
      } catch (err) {
        console.warn("WS: malformed message", err);
      }
    };

    ws.onclose = () => {
      this.ws = null;
      if (this.closed) return;
      const delay = Math.min(this.backoff, MAX_BACKOFF_MS);
      this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
      setTimeout(() => this.connect(), delay);
    };

    ws.onerror = () => {
      // onclose will fire next; nothing to do here.
    };
  }
}
