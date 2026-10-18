import { expect, signIn, skipIntro, test } from "./helpers";

// Preparation: a court session. The panel asks, the founder types, Vicky scores each answer and
// checks every claim against the data and the notes.
const ANSWERS = [
  "Our monthly figures come straight from the income statement on the dashboard. Growth has slowed in recent months, so this quarter we're focused on retention and the reseller channel to bring it back.",
  "Gross margin is high as booked; once customer success costs are counted it drops, and we show both. We'd use the round to hire and extend runway, and every number in the deck has a source.",
];

test.beforeEach(async ({ context, baseURL }) => {
  await signIn(context, baseURL!);
  await skipIntro(context);
});

test("03-preparation", async ({ page, demo }) => {
  await page.goto("/preparation");
  await expect(page.getByRole("heading", { name: "Prepare." })).toBeVisible();
  const roster = page.getByRole("list", { name: "Investors on the panel" });
  await expect(roster.getByRole("button").first()).toBeVisible();
  demo.captionAt = "top";
  demo.begin();
  await demo.pause(800);
  await demo.caption("Preparation", "Rehearse with a panel of investor personas. Vicky chairs, reviews and scores.");
  await demo.pause(1800);
  await demo.hover(roster.getByRole("button").first());
  await demo.hover(roster.getByRole("button").nth(2));
  await demo.pause(600);

  await demo.caption("Session setup", "How many questions, coached or realistic, and checks against the knowledge base.");
  await demo.click(page.getByRole("radio", { name: "Realistic" }));
  await demo.click(page.getByRole("radio", { name: "Coached" }));
  await demo.pause(600);
  await demo.click(page.getByRole("button", { name: "Start session" }));

  const answer = page.getByLabel("Your answer");
  await demo.caption("The court", "The first investor asks, from your numbers and your notes.");
  await demo.fastForward(() => expect(answer).toBeEnabled({ timeout: 120_000 }), 5);
  await demo.pause(3500);

  for (const [i, text] of ANSWERS.entries()) {
    await demo.caption("Answer", i === 0 ? "Type an answer. Vicky scores it and checks each claim against the data." : "Every figure is checked: matches, contradicts, unsupported, or forecast stated as fact.");
    await demo.type(answer, text, 14);
    await answer.press("Enter");
    await demo.fastForward(async () => {
      await expect(answer).toBeDisabled({ timeout: 10_000 }).catch(() => {});
      await expect(answer).toBeEnabled({ timeout: 150_000 });
    }, 6);
    await demo.pause(3500);
    await demo.moveTo(700, 420, 700);
    await demo.scroll(-400);
    await demo.pause(1500);
  }

  // Filter the feed down to Vicky's feedback.
  const tabs = page.getByRole("tablist", { name: "Show" }).getByRole("tab");
  if ((await tabs.count()) > 1) {
    await demo.caption("Feedback", "Filter the court down to Vicky's notes on each answer.");
    await demo.click(tabs.nth(1));
    await demo.pause(3000);
    await demo.click(tabs.first());
    await demo.pause(800);
  }

  await demo.caption("Questions & answers", "Every question collects on the right, to repeat or drill next time.");
  await demo.hover(page.getByRole("heading", { name: "Questions & answers" }));
  await demo.moveTo(1290, 420, 600);
  await demo.pause(2500);

  await demo.caption("End", "Ending the session writes the report: scores, claims, and what to fix.");
  await demo.click(page.getByRole("button", { name: "End", exact: true }));
  await demo.fastForward(() => expect(page.getByRole("button", { name: "End", exact: true })).toHaveCount(0, { timeout: 150_000 }), 6);
  await demo.pause(3000);
  await demo.caption();
  await demo.pause(300);
});
