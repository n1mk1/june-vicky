/**
 * One multiplexed WebSocket per tab to the API's realtime hub (`/api/v1/ws`), shared by every
 * component that subscribes to a channel (`dashboard:{id}`, `session:{id}`).
 *
 * - The web proxy does not carry sockets, so the tab connects to the API's public URL (from
 *   `/api/realtime`) with a short-lived signed token from `/api/v1/realtime/token`.
 * - Envelopes are `{type, channel, version, ts, payload}`; `version` rises per channel, so anything
 *   at or below the last version seen on that channel is a duplicate and is dropped.
 * - Postgres is the record: after a reconnect every channel is told to re-fetch (`onResync`), so a
 *   redeploy or a dropped connection loses nothing.
 */

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

export interface Envelope<P = Record<string, unknown>> {
  type: string;
  channel: string;
  session_id?: string;
  version: number;
  ts?: string;
  payload: P;
}

export type SocketStatus = "idle" | "connecting" | "open" | "reconnecting";

interface Handler {
  onEvent: (e: Envelope) => void;
  onResync?: () => void;
}

const PING_MS = 20_000;
const MAX_BACKOFF_MS = 15_000;

function fallbackWsUrl(): string {
  const { protocol, hostname } = window.location;
  return `${protocol === "https:" ? "wss" : "ws"}://${hostname}:8000`;
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return (await res.json()) as T;
}

class RealtimeSocket {
  private ws: WebSocket | null = null;
  private subs = new Map<string, Set<Handler>>();
  private seen = new Map<string, number>();
  private status: SocketStatus = "idle";
  private listeners = new Set<() => void>();
  private attempt = 0;
  private opened = 0;
  private retry: number | null = null;
  private idle: number | null = null;
  private connecting = false;
  private wired = false;

  getStatus = (): SocketStatus => this.status;

  onStatus = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  subscribe(channel: string, handler: Handler): () => void {
    this.wire();
    if (this.idle !== null) {
      window.clearTimeout(this.idle);
      this.idle = null;
    }
    let set = this.subs.get(channel);
    if (!set) {
      set = new Set();
      this.subs.set(channel, set);
      this.send({ type: "subscribe", channel });
    }
    set.add(handler);
    if (!this.ws && !this.connecting && this.retry === null) void this.connect();
    return () => {
      const s = this.subs.get(channel);
      if (!s) return;
      s.delete(handler);
      if (s.size) return;
      this.subs.delete(channel);
      this.seen.delete(channel);
      this.send({ type: "unsubscribe", channel });
      // Navigating between pages unsubscribes and resubscribes; keep the socket for a moment.
      if (!this.subs.size) this.idle = window.setTimeout(() => this.close(), 5_000);
    };
  }

  private wire() {
    if (this.wired || typeof window === "undefined") return;
    this.wired = true;
    const now = () => {
      if (this.subs.size && !this.ws && !this.connecting) {
        if (this.retry !== null) window.clearTimeout(this.retry);
        this.retry = null;
        this.attempt = 0;
        void this.connect();
      }
    };
    window.addEventListener("online", now);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") now();
    });
  }

  private setStatus(s: SocketStatus) {
    if (this.status === s) return;
    this.status = s;
    this.listeners.forEach((fn) => fn());
  }

  private send(msg: object) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private async connect() {
    if (!this.subs.size) return;
    this.connecting = true;
    this.setStatus(this.opened ? "reconnecting" : "connecting");
    let url: string;
    try {
      const [cfg, tok] = await Promise.all([
        getJson<{ ws_url: string | null }>("/api/realtime"),
        getJson<{ token: string }>("/api/v1/realtime/token"),
      ]);
      const base = (cfg.ws_url || fallbackWsUrl()).replace(/\/+$/, "");
      const qs = new URLSearchParams({ token: tok.token, channels: [...this.subs.keys()].join(",") });
      url = `${base}/api/v1/ws?${qs}`;
    } catch {
      this.connecting = false;
      this.scheduleReconnect();
      return;
    }
    this.connecting = false;
    if (!this.subs.size) return;

    // Another path opened a socket while this one fetched its token: keep that one, never two.
    if (this.ws) {
      if (this.ws.readyState === WebSocket.OPEN) this.setStatus("open");
      return;
    }

    const ws = new WebSocket(url);
    this.ws = ws;
    // Each socket owns its ping timer, so a stale socket closing late can't stop the live one's.
    let ping: number | null = null;
    ws.onopen = () => {
      if (this.ws !== ws) {
        ws.close();
        return;
      }
      this.attempt = 0;
      this.setStatus("open");
      // Channels added while the socket was opening are not in the URL.
      const inUrl = new Set(new URL(url).searchParams.get("channels")?.split(",") ?? []);
      for (const c of this.subs.keys()) if (!inUrl.has(c)) this.send({ type: "subscribe", channel: c });
      ping = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
      }, PING_MS);
    };
    ws.onmessage = (m) => {
      if (this.ws === ws) this.receive(m.data);
    };
    ws.onclose = () => {
      if (ping !== null) window.clearInterval(ping);
      ping = null;
      // A socket already replaced or closed on purpose (close() cleared this.ws): whatever happens
      // next is the current socket's business, so don't schedule a reconnect that would open a second.
      if (this.ws !== ws) return;
      this.ws = null;
      if (this.subs.size) this.scheduleReconnect();
      else this.setStatus("idle");
    };
    ws.onerror = () => ws.close();
  }

  private receive(data: unknown) {
    let msg: { type?: string; channels?: string[]; versions?: Record<string, number> } & Partial<Envelope>;
    try {
      msg = JSON.parse(String(data));
    } catch {
      return;
    }
    if (msg.type === "hello") {
      const reconnect = this.opened > 0;
      this.opened += 1;
      // The server's counters are the baseline from here on (they also reset if Redis was flushed).
      for (const [c, v] of Object.entries(msg.versions ?? {})) this.seen.set(c, v);
      if (reconnect) for (const set of this.subs.values()) set.forEach((h) => h.onResync?.());
      return;
    }
    if (msg.type === "pong" || !msg.channel || typeof msg.version !== "number") return;
    const last = this.seen.get(msg.channel) ?? 0;
    if (msg.version <= last) return; // duplicate or replayed
    this.seen.set(msg.channel, msg.version);
    const env = msg as Envelope;
    this.subs.get(env.channel)?.forEach((h) => h.onEvent(env));
  }

  private scheduleReconnect() {
    if (this.retry !== null || !this.subs.size) return;
    this.setStatus("reconnecting");
    const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** this.attempt) * (0.75 + Math.random() * 0.5);
    this.attempt += 1;
    this.retry = window.setTimeout(() => {
      this.retry = null;
      void this.connect();
    }, delay);
  }

  private close() {
    this.idle = null;
    if (this.subs.size) return;
    this.opened = 0;
    this.ws?.close();
    this.ws = null;
    this.setStatus("idle");
  }
}

let shared: RealtimeSocket | null = null;
const socket = () => (shared ??= new RealtimeSocket());

/**
 * Subscribe this component to a realtime channel while it is mounted. `onEvent` gets each new
 * envelope once (deduped by version); `onResync` runs after a reconnect, to re-fetch from REST.
 */
export function useChannel(channel: string | null, onEvent: (e: Envelope) => void, onResync?: () => void) {
  const ev = useRef(onEvent);
  const rs = useRef(onResync);
  useEffect(() => {
    ev.current = onEvent;
    rs.current = onResync;
  }, [onEvent, onResync]);
  useEffect(() => {
    if (!channel) return;
    return socket().subscribe(channel, { onEvent: (e) => ev.current(e), onResync: () => rs.current?.() });
  }, [channel]);
}

const noop = () => () => {};

/** The shared socket's state, for a "Live" / "Reconnecting" indicator. */
export function useSocketStatus(): SocketStatus {
  const sub = useCallback((fn: () => void) => (typeof window === "undefined" ? noop() : socket().onStatus(fn)), []);
  return useSyncExternalStore(sub, () => socket().getStatus(), () => "idle");
}
