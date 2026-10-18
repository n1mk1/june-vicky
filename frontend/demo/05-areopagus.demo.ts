import { expect, signIn, skipIntro, test } from "./helpers";

// Areopagus: the investor personas the panel is drawn from, and the builder that drafts a new one
// from a description. The draft is cancelled, so nothing is saved.
test.beforeEach(async ({ context, baseURL }) => {
  await signIn(context, baseURL!);
  await skipIntro(context);
});

test("05-areopagus", async ({ page, demo }) => {
  await page.goto("/areopagus");
  const cards = page.getByRole("list", { name: "Investors" }).getByRole("article");
  await expect(cards.first()).toBeVisible();
  demo.begin();
  await demo.pause(800);
  await demo.caption("Areopagus", "The investor personas: each with a lens, a style, opening questions and dealbreakers.");
  await demo.pause(1800);
  const n = Math.min(await cards.count(), 4);
  for (let i = 0; i < n; i++) {
    await demo.hover(cards.nth(i), 700);
    await demo.pause(1700);
  }

  await demo.caption("New investor", "Describe an investor in a sentence; Claude drafts the persona, you check every field.");
  await demo.click(page.getByRole("button", { name: "New investor" }));
  const builder = page.getByRole("dialog", { name: "New investor" });
  await expect(builder).toBeVisible();
  const describe = builder.getByLabel("Describe the investor");
  await demo.type(
    describe,
    "A climate-focused seed investor who cares about unit economics and asks hard questions about churn and payback.",
    18,
  );
  await demo.click(builder.getByRole("button", { name: "Generate" }));
  await demo.fastForward(() => expect(builder.getByLabel("Name")).toHaveValue(/\S/, { timeout: 120_000 }), 5);
  await demo.pause(1500);
  await demo.moveTo(1000, 520, 700);
  await demo.scroll(700, 1500);
  await demo.pause(1200);
  await demo.scroll(700, 1500);
  await demo.pause(1500);

  await demo.click(builder.getByRole("button", { name: "Cancel" }));
  await demo.pause(1200);
  await demo.caption();
  await demo.pause(300);
});
