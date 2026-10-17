/**
 * Where the web server reaches the API. Read at request time, never baked into the build,
 * so one image works locally (http://localhost:8000), in compose (http://api:8000) and on
 * Render, whose `hostport` reference has no scheme (vicky-api:10000).
 */
export function apiOrigin(): string {
  const raw = (process.env.API_INTERNAL_URL || "http://localhost:8000").trim().replace(/\/+$/, "");
  return /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
}

/** Public WebSocket origin for the browser (the API's own URL; the web proxy does not carry sockets). */
export function apiPublicWsUrl(): string | null {
  const raw = process.env.API_PUBLIC_WS_URL?.trim();
  return raw ? raw.replace(/\/+$/, "") : null;
}
