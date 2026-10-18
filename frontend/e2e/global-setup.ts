import { request, type FullConfig } from "@playwright/test";
import { mkdirSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

/** Sign in once and make sure there is a confirmed source of truth to test against. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0].use.baseURL ?? "http://localhost:3000";
  const ctx = await request.newContext({ baseURL });
  const access = await ctx.post("/api/v1/auth/access", { data: { code: process.env.ACCESS_CODE ?? "vicky-demo" } });
  if (!access.ok()) throw new Error(`Sign-in failed (${access.status()}). Is the stack running at ${baseURL}?`);

  const active = await ctx.get("/api/v1/engagements/active");
  if (active.status() === 404) {
    // Like a founder would: put a sample company's files in the knowledge base, fill, confirm.
    const dir = join(process.cwd(), "..", "backend", "data", "samples", process.env.E2E_SAMPLE ?? "harbor-labs");
    const form = new FormData();
    for (const f of readdirSync(dir).filter((name) => name.toLowerCase().endsWith(".csv"))) {
      form.append("files", new Blob([readFileSync(join(dir, f))], { type: "text/csv" }), f);
    }
    const imported = await ctx.post("/api/v1/kb/import", { multipart: form });
    if (!imported.ok()) throw new Error(`Could not import the sample (${imported.status()})`);
    for (let i = 0; i < 120; i++) {
      const st = (await (await ctx.get("/api/v1/kb/status")).json()) as { running: boolean };
      if (!st.running) break;
      await new Promise((r) => setTimeout(r, 1000));
    }
    const filled = await ctx.post("/api/v1/kb/autofill", { timeout: 180_000 });
    if (!filled.ok()) throw new Error(`Could not fill the dashboard (${filled.status()})`);
    const { engagement } = (await filled.json()) as { engagement: { id: string } };
    const ok = await ctx.post(`/api/v1/engagements/${engagement.id}/confirm`);
    if (!ok.ok()) throw new Error(`Could not confirm the sample (${ok.status()})`);
  } else if (!active.ok()) {
    throw new Error(`Could not read the active engagement (${active.status()})`);
  }

  mkdirSync("e2e/.auth", { recursive: true });
  await ctx.storageState({ path: "e2e/.auth/state.json" });
  await ctx.dispose();
}
