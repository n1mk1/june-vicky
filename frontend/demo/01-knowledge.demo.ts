import { expect, signIn, skipIntro, test } from "./helpers";

// Knowledge base: the vault, its graph, a table and a document Vicky read, and search.
test.beforeEach(async ({ context, baseURL }) => {
  await signIn(context, baseURL!);
  await skipIntro(context);
});

test("01-knowledge", async ({ page, demo }) => {
  await page.goto("/knowledge");
  const tree = page.getByRole("navigation", { name: "Notes" });
  await expect(tree.getByRole("button").first()).toBeVisible();
  await expect(page.getByRole("img", { name: /graph of the knowledge base/i })).toBeVisible();
  demo.begin();
  await demo.pause(800);
  await demo.caption("Knowledge base", "Every file the founder imports: CSVs, PDFs, decks, notes. OCR'd, organized and linked.");
  await demo.pause(1800);

  // The graph: hubs, documents, tables and the links between them.
  const graph = page.getByRole("img", { name: /graph of the knowledge base/i });
  const g = (await graph.boundingBox())!;
  await demo.moveTo(g.x + g.width * 0.42, g.y + g.height * 0.45, 900);
  await demo.moveTo(g.x + g.width * 0.62, g.y + g.height * 0.38, 900);
  await demo.moveTo(g.x + g.width * 0.55, g.y + g.height * 0.62, 900);
  await demo.pause(800);

  // A table: the numbers the metrics engine computes from.
  await demo.caption("Tables", "Spreadsheets stay tables. The metrics engine computes every figure from them, never the model.");
  const table = tree.getByRole("button", { name: /income statement/i }).first();
  await demo.click(table);
  await expect(page.getByLabel("Note title")).toBeVisible();
  await demo.pause(1800);
  await demo.moveTo(820, 560, 700);
  await demo.scroll(500);
  await demo.pause(800);

  // A hub note that links the folder together.
  await demo.caption("Hubs", "The organizer writes a hub per folder with [[links]] to everything in it.");
  await demo.click(tree.getByRole("button", { name: "Financials", exact: true }));
  await demo.pause(2200);

  // A long document, read into markdown.
  const doc = tree.getByRole("button", { name: /pack|deck|memo|report/i }).first();
  if (await doc.count()) {
    await demo.caption("Documents", "PDFs and decks are converted to markdown (with OCR for scans) so Vicky can cite them.");
    await demo.click(doc);
    await demo.pause(1600);
    await demo.moveTo(820, 560, 700);
    await demo.scroll(900, 1400);
    await demo.pause(800);
  }

  // Search across the vault.
  await demo.caption("Search", "Hybrid search (BM25 + pgvector) over every note, rebuilt on each Fill.");
  await demo.type(page.getByRole("searchbox", { name: "Search notes" }), "revenue");
  await demo.pause(2000);
  const close = page.getByRole("button", { name: "Close note" });
  if (await close.isVisible()) await demo.click(close);

  await demo.caption("Fill dashboard", "One click fills the dashboard from the knowledge base; the founder confirms it.");
  await demo.hover(page.getByRole("button", { name: "Fill dashboard" }));
  await demo.pause(2200);
  await demo.caption();
  await demo.pause(300);
});
