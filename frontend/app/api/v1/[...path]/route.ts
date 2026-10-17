import type { NextRequest } from "next/server";
import { apiOrigin } from "@/lib/server/api-origin";

/**
 * Same-origin proxy: /api/v1/* on the web service → the API's /api/v1/*. The browser only ever
 * talks to the web origin, so the access cookie stays first-party. Request bodies (multipart
 * uploads included) and responses (SSE included) are streamed, not buffered.
 */

// Hop-by-hop headers must not be forwarded (RFC 9110 §7.6.1); host/length are set by fetch.
const HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
  "transfer-encoding", "upgrade", "host", "content-length", "accept-encoding",
]);

async function proxy(req: NextRequest, ctx: RouteContext<"/api/v1/[...path]">): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${apiOrigin()}/api/v1/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  headers.set("x-forwarded-host", req.headers.get("host") ?? "");
  headers.set("x-forwarded-proto", req.nextUrl.protocol.replace(":", ""));

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      redirect: "manual",
      cache: "no-store",
      signal: req.signal,
      // Required by Node's fetch to stream a request body.
      ...(hasBody ? { duplex: "half" } : {}),
    } as RequestInit);
  } catch {
    return Response.json(
      { detail: "The Vicky API is not reachable. It may be waking up; try again in a minute." },
      { status: 502 },
    );
  }

  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (!HOP.has(k) && k !== "content-encoding" && k !== "set-cookie") out.set(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);
  if (out.get("content-type")?.startsWith("text/event-stream")) out.set("x-accel-buffering", "no");

  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
