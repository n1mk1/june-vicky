import { connection } from "next/server";
import { apiOrigin } from "@/lib/server/api-origin";

/** Web health plus a short probe of the API (also wakes a sleeping free-tier API on landing). */
export async function GET() {
  await connection();
  let api: unknown = "unreachable";
  try {
    const res = await fetch(`${apiOrigin()}/healthz`, { cache: "no-store", signal: AbortSignal.timeout(4000) });
    api = res.ok ? await res.json() : `http ${res.status}`;
  } catch {}
  return Response.json({ web: "ok", api });
}
