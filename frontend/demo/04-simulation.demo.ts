import { expect, signIn, skipIntro, test } from "./helpers";

// Simulation: the pitch room. The founder pitches, the panel questions afterwards, and the claims
// ledger fills as they talk. Recorded with typing in place of the microphone.
const PITCH = [
  "We build scheduling and dispatch software for small field-service businesses, sold as a monthly subscription.",
  "Revenue has grown every quarter since launch and gross margin is high; every figure in this pitch is on our dashboard with its source.",
  "We're raising a seed round to hire, grow the reseller channel, and extend runway.",
];
const REPLY = "Growth has slowed recently, and we say so. The plan is retention first, then the reseller channel; the dashboard shows both trends with their sources.";

test.beforeEach(async ({ context, baseURL }) => {
  await signIn(context, baseURL!);
  await skipIntro(context);
  // No microphone in a recording: the room falls back to typing, as it does in browsers without one.
  await context.addInitScript(() => {
    if (navigator.mediaDevices) Object.defineProperty(navigator.mediaDevices, "getUserMedia", { value: undefined });
  });
});

test("04-simulation", async ({ page, demo }) => {
  await page.goto("/simulation");
  const main = page.getByTestId("sim-mic");
  await expect(main).toBeEnabled({ timeout: 30_000 });
  demo.captionAt = "top";
  demo.begin();
  await demo.pause(800);
  await demo.caption("Simulation", "The pitch room: present to the panel, then take their questions, live or after.");
  await demo.pause(2000);
  await demo.hover(page.getByRole("radio", { name: "Interrupt live" }));
  await demo.hover(page.getByRole("radio", { name: "Questions after" }));
  await demo.caption("Your deck", "Upload a PDF or PowerPoint and every figure on it is checked before you start.");
  await demo.hover(page.getByTestId("deck-upload"));
  await demo.pause(1800);

  await demo.caption("Start", "Vicky opens the room; the panel's lines show as captions.");
  await demo.click(main);
  const typed = page.getByLabel("Type what you'd say");
  await demo.fastForward(() => expect(typed).toBeEnabled({ timeout: 120_000 }), 4);
  await demo.pause(1200);

  await demo.caption("Pitch", "Say it (or type it). Claims land in the ledger on the right as you go.");
  for (const line of PITCH) {
    await demo.type(typed, line, 16);
    await typed.press("Enter");
    await demo.fastForward(() => expect(typed).toBeEnabled({ timeout: 90_000 }), 4);
    await demo.pause(900);
  }
  await demo.hover(page.getByRole("region", { name: "Scoring and metrics" }));
  await demo.pause(1500);

  await demo.caption("Q&A", "End the pitch and the panel confers, then asks.");
  await demo.click(page.getByRole("button", { name: "End", exact: true }));
  await demo.fastForward(() => expect(typed).toBeEnabled({ timeout: 180_000 }), 6);
  await demo.pause(2500);
  await demo.caption("Answer", "Each answer is scored: accuracy, evidence, clarity, composure, investor fit.");
  await demo.type(typed, REPLY, 16);
  await typed.press("Enter");
  await demo.fastForward(() => expect(typed).toBeEnabled({ timeout: 180_000 }), 6);
  await demo.pause(2500);

  await demo.caption("Done", "End the Q&A and the session is written up as a report.");
  await demo.click(page.getByRole("button", { name: "End Q&A" }));
  await demo.fastForward(() => expect(page.getByRole("button", { name: "New pitch" })).toBeVisible({ timeout: 180_000 }), 6);
  await demo.pause(1200);
  await demo.hover(page.getByRole("region", { name: "Scoring and metrics" }));
  await demo.pause(2500);
  const report = page.getByRole("link", { name: "Open the report" });
  if (await report.count()) await demo.hover(report);
  await demo.pause(2000);
  await demo.caption();
  await demo.pause(300);
});
