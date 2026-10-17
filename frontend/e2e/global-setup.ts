import { request, type FullConfig } from "@playwright/test";
import { mkdirSync } from "node:fs";

/** Sign in once and make sure there is a confirmed source of truth to test against. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL ?? "http://localhost:3000";
  const ctx = await request.newContext({ baseURL });
  const access = await ctx.post("/api/v1/auth/access", { data: { code: process.env.ACCESS_CODE ?? "vicky-demo" } });
  if (!access.ok()) throw new Error(`Sign-in failed (${access.status()}). Is the stack running at ${baseURL}?`);

  const active = await ctx.get("/api/v1/engagements/active");
  if (active.status() === 404) {
    const samples = (await (await ctx.get("/api/v1/samples")).json()) as { id: string }[];
    const sample = samples.find((s) => s.id === (process.env.E2E_SAMPLE ?? "")) ?? samples[0];
    const eng = (await (await ctx.post(`/api/v1/samples/${sample.id}/load`)).json()) as { id: string };
    const ok = await ctx.post(`/api/v1/engagements/${eng.id}/confirm`);
    if (!ok.ok()) throw new Error(`Could not confirm the sample (${ok.status()})`);
  } else if (!active.ok()) {
    throw new Error(`Could not read the active engagement (${active.status()})`);
  }

  mkdirSync("e2e/.auth", { recursive: true });
  await ctx.storageState({ path: "e2e/.auth/state.json" });
  await ctx.dispose();
}
