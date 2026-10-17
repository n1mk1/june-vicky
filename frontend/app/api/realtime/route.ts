import { connection } from "next/server";
import { apiPublicWsUrl } from "@/lib/server/api-origin";

/**
 * Where the browser opens its WebSocket. The web proxy does not carry sockets, so tabs connect to
 * the API directly; the URL is read at request time so one image works everywhere.
 */
export async function GET() {
  await connection();
  return Response.json({ ws_url: apiPublicWsUrl() }, { headers: { "cache-control": "no-store" } });
}
