/**
 * Browser client for the Vik API. Every call goes through the same-origin proxy at
 * /api/v1/*, so the access cookie is sent automatically.
 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public body?: unknown,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  /** The access cookie is missing or expired; show the access-code gate. */
  get needsAccess() {
    return this.status === 401;
  }

  /** The daily LLM budget is spent. */
  get overBudget() {
    return this.status === 402;
  }
}

type Json = Record<string, unknown> | unknown[];

export interface ApiOptions extends Omit<RequestInit, "body"> {
  /** JSON body (serialized) or FormData (sent as multipart). */
  body?: Json | FormData;
  query?: Record<string, string | number | boolean | undefined | null>;
}

function url(path: string, query?: ApiOptions["query"]): string {
  const clean = path.replace(/^\/+/, "");
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null) qs.set(k, String(v));
  const s = qs.toString();
  return `/api/v1/${clean}${s ? `?${s}` : ""}`;
}

async function detailOf(res: Response): Promise<{ detail: string; body?: unknown }> {
  const text = await res.text().catch(() => "");
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    const d = body?.detail;
    // FastAPI's request validation answers with a list of {loc, msg, input}: show the messages, not the JSON.
    const msgs = Array.isArray(d) ? d.map((e) => (e as { msg?: unknown })?.msg).filter((m): m is string => typeof m === "string") : [];
    const detail = typeof d === "string" ? d : msgs.length ? msgs.join("; ") : d ? JSON.stringify(d) : res.statusText;
    return { detail, body };
  } catch {
    // An HTML page is the host's own error page (a sleeping or restarting API), not a message from the API.
    if (/^\s*</.test(text) || (res.headers.get("content-type") ?? "").includes("text/html")) return { detail: "" };
    return { detail: text || res.statusText };
  }
}

export async function api<T = unknown>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { body, query, headers, ...rest } = opts;
  const h = new Headers(headers);
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    payload = JSON.stringify(body);
    h.set("content-type", "application/json");
  }
  if (!h.has("accept")) h.set("accept", "application/json");

  const res = await fetch(url(path, query), { credentials: "same-origin", ...rest, headers: h, body: payload });
  if (!res.ok) {
    const { detail, body: errBody } = await detailOf(res);
    throw new ApiError(res.status, detail, errBody);
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const apiGet = <T>(path: string, query?: ApiOptions["query"]) => api<T>(path, { query });
export const apiPost = <T>(path: string, body?: Json | FormData) => api<T>(path, { method: "POST", body });
export const apiPut = <T>(path: string, body?: Json) => api<T>(path, { method: "PUT", body });
export const apiPatch = <T>(path: string, body?: Json) => api<T>(path, { method: "PATCH", body });
export const apiDelete = <T>(path: string) => api<T>(path, { method: "DELETE" });

/** Exchange the shared access code for the signed cookie (FR-14). */
export const enterAccessCode = (code: string) => apiPost<{ ok: boolean }>("auth/access", { code });
