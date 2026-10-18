import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// The knowledge base end to end in the browser: the landing's way in, the tab order, importing,
// reading and following links, editing (autosave), renaming, tags, ghost links, search, organize,
// export, delete, drag-and-drop and "Fill dashboard". Every note this run makes carries RUN in its
// name and is deleted afterwards. Expectations hold for both organizers (Claude or offline rules).

const RUN = `e2e${Date.now().toString(36)}`;
const JOB_MS = 60_000;

const CSV = `Month,Subscription revenue,COGS,Cash\n2025-01,42000,9000,910000\n2025-02,45500,9400,880000\n2025-03,49000,9900,851000\n`;
const MD = (run: string) =>
  `# ${run} plan\n\nWe are raising a seed round on a SAFE. The [[${run} pnl]] shows the trend.\nStill to write: [[${run} interviews]].\n`;

/** A one-page PDF with a text layer, so the run needs no PDF library. */
function pdf(lines: string[]): Buffer {
  const content = "BT /F1 12 Tf 72 720 Td 14 TL " + lines.map((l) => `(${l}) Tj T*`).join(" ") + " ET";
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let out = "%PDF-1.4\n";
  const offs: number[] = [];
  objs.forEach((o, i) => {
    offs.push(out.length);
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("");
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF`;
  return Buffer.from(out, "latin1");
}

interface Note {
  id: string;
  path: string;
  title: string;
  kind: string;
}

async function runNotes(api: APIRequestContext): Promise<Note[]> {
  const r = await api.get("/api/v1/kb/notes");
  expect(r.ok()).toBeTruthy();
  return ((await r.json()) as Note[]).filter((n) => n.title.includes(RUN) || n.path.includes(RUN));
}

/** Wait until the import/organize job has finished and the vault reloaded. */
async function settled(page: Page) {
  await expect(page.getByText(/Done:/)).toBeVisible({ timeout: JOB_MS });
}

async function openNote(page: Page, title: string | RegExp) {
  await page.getByRole("navigation", { name: "Notes" }).getByRole("button", { name: title }).first().click();
  await expect(page.getByLabel("Note title")).toHaveValue(title instanceof RegExp ? title : title);
}

test.describe.configure({ mode: "serial" });
test.use({ viewport: { width: 1440, height: 900 } });

test.afterAll(async ({ request }) => {
  for (const n of await runNotes(request)) await request.delete(`/api/v1/kb/notes/${n.id}`);
});

test("landing is black and white, has no chat, and GET STARTED opens the knowledge base", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "JUNE × VICKY" })).toBeVisible();
  await expect(page.getByText("Know Your Numbers Before They Do")).toBeVisible();
  await expect(page.locator("main textarea, main input")).toHaveCount(0);
  expect(await page.locator("main").evaluate((m) => getComputedStyle(m).backgroundColor)).toBe("rgb(0, 0, 0)");
  // The ASCII V: a canvas with digits drawn on it, changing between frames (the flicker).
  const canvas = page.locator("main canvas");
  await expect(canvas).toBeVisible();
  const frame = () => canvas.evaluate((c: HTMLCanvasElement) => c.toDataURL());
  const first = await frame();
  await page.waitForTimeout(600);
  expect(await frame()).not.toEqual(first);
  await page.getByRole("link", { name: "Get started" }).click();
  await expect(page).toHaveURL(/\/knowledge$/);
});

test("tabs run Knowledge base → Reports and the flagships stand out", async ({ page }) => {
  await page.goto("/knowledge");
  const tabs = page.getByRole("navigation", { name: "Sections" }).getByRole("link");
  await expect(tabs).toHaveText([/knowledge base/i, /dashboard/i, /preparation/i, /simulation/i, /areopagus/i, /reports/i]);
  const flagship = await tabs.evaluateAll((els) => els.map((e) => e.hasAttribute("data-flagship")));
  expect(flagship).toEqual([false, true, true, true, false, false]);
  const colour = (i: number) => tabs.nth(i).evaluate((e) => getComputedStyle(e).borderColor);
  expect(await colour(1)).not.toEqual(await colour(4));
  await expect(tabs.first()).toHaveAttribute("aria-current", "page");
});

test("import converts, files and links the notes", async ({ page, request }) => {
  await page.goto("/knowledge");
  await page.getByLabel("Import files").setInputFiles([
    { name: `${RUN} pnl.csv`, mimeType: "text/csv", buffer: Buffer.from(CSV) },
    { name: `${RUN} plan.md`, mimeType: "text/markdown", buffer: Buffer.from(MD(RUN)) },
    { name: `${RUN} customers.json`, mimeType: "application/json", buffer: Buffer.from(JSON.stringify([{ name: "A", mrr: 1 }, { name: "B", mrr: 2 }])) },
    { name: `${RUN} memo.pdf`, mimeType: "application/pdf", buffer: pdf([`${RUN} investment memo`, "Recurring revenue grew each month."]) },
    { name: `${RUN} market.html`, mimeType: "text/html", buffer: Buffer.from(`<title>${RUN} market</title><p>Billing tools are a crowded market.</p>`) },
  ]);
  await expect(page.getByText(/5 files added/)).toBeVisible({ timeout: JOB_MS });
  await settled(page);

  const notes = await runNotes(request);
  expect(notes.map((n) => n.kind).sort()).toEqual(["document", "document", "note", "table", "table"]);
  expect(notes.every((n) => !n.path.startsWith("inbox/"))).toBeTruthy(); // the organizer filed them
  for (const n of notes) await expect(page.getByRole("navigation", { name: "Notes" }).getByRole("button", { name: n.title, exact: true })).toBeVisible();
  await expect(page.locator("main canvas").first()).toBeVisible();
  await expect(page.getByText(/\d+ nodes · \d+ links/)).toBeVisible();

  // The same files again are skipped as duplicates.
  await page.getByLabel("Import files").setInputFiles([{ name: `${RUN} pnl copy.csv`, mimeType: "text/csv", buffer: Buffer.from(CSV) }]);
  await expect(page.getByText(/1 already in the knowledge base, skipped/)).toBeVisible({ timeout: JOB_MS });
});

test("reading: wikilinks open notes, tables render, backlinks show", async ({ page }) => {
  await page.goto("/knowledge");
  await openNote(page, new RegExp(`${RUN} plan`, "i"));
  const link = page.locator(".kb-wikilink", { hasText: `${RUN} pnl` });
  await expect(link).not.toHaveClass(/kb-wikilink-missing/);
  await expect(page.locator(".kb-wikilink-missing", { hasText: `${RUN} interviews` })).toBeVisible();
  await link.click();
  await expect(page.getByLabel("Note title")).toHaveValue(new RegExp(`${RUN} pnl`, "i"));
  await expect(page.getByRole("columnheader", { name: /subscription revenue/i })).toBeVisible();
  await expect(page.getByRole("cell", { name: "45500" })).toBeVisible();
  await expect(page.getByText(/Linked from · \d/)).toBeVisible();

  // On a phone the page never scrolls sideways: the wide table scrolls inside its panel.
  const sideways = () => page.evaluate(() => document.scrollingElement!.scrollWidth - document.scrollingElement!.clientWidth);
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(page.getByRole("cell", { name: "45500" })).toBeAttached();
  expect(await sideways(), "sideways scroll with a table open").toBeLessThanOrEqual(0);
  await page.getByRole("button", { name: "Close note" }).click();
  await expect(page.getByLabel("Note title")).toHaveCount(0);
  expect(await sideways(), "sideways scroll on the vault").toBeLessThanOrEqual(0);
});

test("editing autosaves, survives a reload and adds a graph link", async ({ page }) => {
  await page.goto("/knowledge");
  const before = Number((await page.getByText(/\d+ nodes · \d+ links/).textContent())?.match(/(\d+) links/)?.[1]);
  await openNote(page, new RegExp(`${RUN} plan`, "i"));
  await page.getByRole("radio", { name: "Edit" }).click();
  const editor = page.getByLabel("Note content");
  await editor.click();
  await editor.press("Control+End");
  await editor.pressSequentially(`\nAlso see [[${RUN} memo]].`);
  await expect(page.getByText(/^Saved /)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(new RegExp(`(\\d+) links`))).not.toHaveText(new RegExp(`${before} links`), { timeout: 10_000 });
  await page.reload();
  await expect(page.getByLabel("Note title")).toBeVisible();
  await page.getByRole("radio", { name: "Edit" }).click();
  await expect(page.getByLabel("Note content")).toHaveValue(new RegExp(`Also see \\[\\[${RUN} memo\\]\\]`));
});

test("rename, tags and a ghost link that creates its note", async ({ page, request }) => {
  await page.goto("/knowledge");
  await openNote(page, new RegExp(`${RUN} plan`, "i"));
  const title = page.getByLabel("Note title");
  await title.fill(`${RUN} fundraising plan`);
  await title.press("Enter");
  await expect(page.getByRole("navigation", { name: "Notes" }).getByRole("button", { name: `${RUN} fundraising plan`, exact: true })).toBeVisible();

  const tag = page.getByLabel("Add a tag");
  await tag.fill("Board Prep");
  await tag.press("Enter");
  await expect(page.getByText("#board-prep")).toBeVisible();
  await page.getByLabel("Remove tag board-prep").click();
  await expect(page.getByText("#board-prep")).toHaveCount(0);

  await page.getByRole("radio", { name: "Read" }).click();
  await page.locator(".kb-wikilink-missing", { hasText: `${RUN} interviews` }).click();
  await expect(page.getByLabel("Note title")).toHaveValue(`${RUN} interviews`);
  await expect(page.getByLabel("Note content")).toBeVisible(); // a new note opens in edit mode
  expect((await runNotes(request)).some((n) => n.title === `${RUN} interviews`)).toBeTruthy();
});

test("double-clicking New note makes one note", async ({ page, request }) => {
  const creates = (r: { method: () => string; url: () => string }) => r.method() === "POST" && new URL(r.url()).pathname === "/api/v1/kb/notes";
  let sent = 0;
  const made: string[] = [];
  page.on("request", (r) => {
    if (creates(r)) sent++;
  });
  page.on("response", async (r) => {
    if (creates(r.request()) && r.ok()) made.push(((await r.json()) as Note).id);
  });
  try {
    await page.goto("/knowledge");
    await expect(page.getByRole("navigation", { name: "Notes" })).toBeVisible();
    await page.getByRole("button", { name: "New note", exact: true }).dblclick();
    await expect(page.getByLabel("Note title")).toHaveValue("Untitled");
    await page.waitForTimeout(1000); // a second create, if one went out, has answered by now
    expect(sent).toBe(1);
  } finally {
    for (const id of made) await request.delete(`/api/v1/kb/notes/${id}`);
  }
});

test("search filters titles and finds words inside notes", async ({ page }) => {
  await page.goto("/knowledge");
  const search = page.getByLabel("Search notes");
  await search.fill(`${RUN} memo`);
  const tree = page.getByRole("navigation", { name: "Notes" });
  await expect(tree.getByRole("button", { name: new RegExp(`^${RUN} memo`, "i") })).toBeVisible();
  await expect(tree.getByRole("button", { name: new RegExp(`${RUN} pnl`, "i") })).toHaveCount(0);
  await search.fill("crowded");
  await expect(page.getByText("In note contents")).toBeVisible({ timeout: 10_000 });
});

test("organize re-files everything and export downloads the vault", async ({ page }) => {
  await page.goto("/knowledge");
  await page.getByRole("button", { name: "Organize", exact: true }).click();
  await expect(page.getByText(/re-organized/)).toBeVisible({ timeout: JOB_MS });
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^vicky-knowledge-base-\d{4}-\d{2}-\d{2}\.zip$/);
});

test("drag-and-drop imports, delete removes a note", async ({ page, request }) => {
  await page.goto("/knowledge");
  // A production build streams the page in: wait for the vault UI (and its drop handlers) first.
  await expect(page.getByRole("button", { name: "New note", exact: true })).toBeEnabled();
  await page.evaluate(async (run) => {
    const dt = new DataTransfer();
    dt.items.add(new File([`# ${run} dropped\n\nDropped onto the page.`], `${run} dropped.md`, { type: "text/markdown" }));
    const target = document.querySelector("main > div")!;
    for (const type of ["dragenter", "dragover", "drop"]) target.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }));
  }, RUN);
  await expect(page.getByText(/1 file added/)).toBeVisible({ timeout: JOB_MS });
  await settled(page);
  await openNote(page, `${RUN} dropped`);
  await page.getByRole("button", { name: "Delete note" }).click();
  await page.getByRole("button", { name: "Confirm delete note" }).click();
  await expect(page.getByRole("navigation", { name: "Notes" }).getByRole("button", { name: `${RUN} dropped` })).toHaveCount(0);
  expect((await runNotes(request)).some((n) => n.title === `${RUN} dropped`)).toBeFalsy();
});

test("Fill dashboard builds a draft source of truth from the vault", async ({ page }) => {
  test.setTimeout(150_000);
  await page.goto("/knowledge");
  await page.getByRole("button", { name: "Fill dashboard", exact: true }).click();
  await expect(page).toHaveURL(/\/knowledge\/confirm\?e=[\w-]+&step=1/, { timeout: 120_000 });
  await expect(page.getByText(/filled these in from your knowledge base/i)).toBeVisible();
  await page.getByRole("button", { name: /02 Mapping/i }).click();
  await expect(page.getByText(new RegExp(`${RUN} pnl`, "i")).first()).toBeVisible();
});
