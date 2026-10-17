import { FIGURES } from "./tidewell";

export type Glyph = "squares" | "orbit" | "slash" | "custom";
export type Temperature = "warming" | "steady" | "cooling";

export interface Persona {
  id: string;
  name: string;
  firm: string;
  lens: string;
  move: string;
  glyph: Glyph;
  temperature: Temperature;
  builtin: boolean;
}

/** Display names from the wireframe, mapped onto the plan's built-in Areopagus personas. */
export const PANEL: Persona[] = [
  {
    id: "lead-seed",
    name: "James",
    firm: "Lead Seed Fund",
    lens: "Metric definitions, retention and burn",
    move: "Follows one number down three levels",
    glyph: "squares",
    temperature: "steady",
    builtin: true,
  },
  {
    id: "angel-operator",
    name: "Alex",
    firm: "Angel Operator",
    lens: "Customers and the sales motion",
    move: "Asks about the last customer who left",
    glyph: "orbit",
    temperature: "cooling",
    builtin: true,
  },
  {
    id: "skeptic",
    name: "Mark",
    firm: "Skeptical Partner",
    lens: "The one claim that breaks the story",
    move: "Interrupts and asks “so what?”",
    glyph: "slash",
    temperature: "warming",
    builtin: true,
  },
];

export type ClaimStatus = "matches" | "contradicts" | "unsupported" | "forecast_as_fact";

export const CLAIM_LABEL: Record<ClaimStatus, string> = {
  matches: "Matches",
  contradicts: "Contradicts",
  unsupported: "Unsupported",
  forecast_as_fact: "Forecast as fact",
};

export interface Dim {
  label: string;
  value: number | null;
}

export type Msg =
  | { id: string; kind: "vc"; vc: string; text: string }
  | { id: string; kind: "founder"; text: string }
  | { id: string; kind: "score"; dims: Dim[]; note: string; claim?: { status: ClaimStatus; text: string } }
  | { id: string; kind: "slide"; slide: number; title: string; note: string }
  | { id: string; kind: "knowledge"; term: string; text: string; source: string };

const dims = (a: number, e: number, c: number, comp: number | null, fit: number): Dim[] => [
  { label: "Accuracy", value: a },
  { label: "Evidence", value: e },
  { label: "Clarity", value: c },
  { label: "Composure", value: comp },
  { label: "Investor fit", value: fit },
];

export const PREP_THREAD: Msg[] = [
  {
    id: "m1",
    kind: "vc",
    vc: "lead-seed",
    text: `Your ARR is ${FIGURES.arr.display}. Is that September subscription revenue times twelve, or are onboarding fees in there too?`,
  },
  {
    id: "m2",
    kind: "founder",
    text: `September subscription revenue, ${FIGURES.mrr.display}, times twelve. Onboarding fees are excluded because they're one-time.`,
  },
  {
    id: "m3",
    kind: "score",
    dims: dims(5, 4, 5, null, 4),
    note: "Right method, and you named the month. Say that one-time fees are excluded before anyone asks.",
    claim: { status: "matches", text: `ARR ${FIGURES.arr.display}` },
  },
  {
    id: "m4",
    kind: "vc",
    vc: "skeptic",
    text: "Your deck says growth is 10% a month. Which months does that cover?",
  },
  { id: "m5", kind: "founder", text: "That's our average. We've been growing about 10% month over month all year." },
  {
    id: "m6",
    kind: "score",
    dims: dims(1, 1, 3, 2, 2),
    note: `Compound monthly growth over 12 months is ${FIGURES.growth12.display}, and ${FIGURES.growth2.display} over the last two. Lead with the 12-month figure and explain the slowdown yourself.`,
    claim: { status: "contradicts", text: "10% monthly growth" },
  },
  {
    id: "m7",
    kind: "slide",
    slide: 2,
    title: "Traction",
    note: `Replace “10% MoM” with “${FIGURES.growth12.display} monthly growth over 12 months” and footnote the last-two-month rate.`,
  },
  { id: "m8", kind: "vc", vc: "angel-operator", text: "Tell me about the last customer who churned. Why did they leave?" },
  { id: "m9", kind: "founder", text: "I'd have to check. I think it was a small clinic." },
  {
    id: "m10",
    kind: "knowledge",
    term: "Net revenue retention",
    text: `Revenue kept from last year's customers, including expansion, minus churn and downgrades. Yours is ${FIGURES.nrr.display}. Below 100% means the existing base is shrinking.`,
    source: FIGURES.nrr.source,
  },
];

export const FOLLOW_UPS = [
  { vc: "lead-seed", text: "Which months does that cover, and where does the figure come from?" },
  { vc: "skeptic", text: "So what? Why does that change whether I'd take a second meeting?" },
  { vc: "angel-operator", text: "Give me one customer story that shows it." },
];

export interface QA {
  id: string;
  vc: string;
  question: string;
  answer: string;
  score: number | null;
  status: ClaimStatus | "open";
}

export const QUESTIONS: QA[] = [
  {
    id: "q1",
    vc: "lead-seed",
    question: "How is ARR calculated?",
    answer: "September subscription × 12, fees excluded.",
    score: 4.5,
    status: "matches",
  },
  {
    id: "q2",
    vc: "skeptic",
    question: "Which months does 10% growth cover?",
    answer: "Claimed 10% all year.",
    score: 1.8,
    status: "contradicts",
  },
  {
    id: "q3",
    vc: "angel-operator",
    question: "Who was the last customer to churn?",
    answer: "Didn't know.",
    score: 1.5,
    status: "unsupported",
  },
  {
    id: "q4",
    vc: "lead-seed",
    question: "What's your burn multiple without SR&ED?",
    answer: "Not asked yet.",
    score: null,
    status: "open",
  },
];

export interface Slide {
  n: number;
  title: string;
  headline: string;
  body: string;
  claim?: { text: string; status: ClaimStatus; truth: string };
}

export const DECK: Slide[] = [
  { n: 1, title: "Tidewell Systems", headline: "Seed round", body: "Raising $4M." },
  {
    n: 2,
    title: "Traction",
    headline: "$1.3M ARR",
    body: "Growing 10% month over month.",
    claim: { text: "10% monthly growth", status: "contradicts", truth: `${FIGURES.growth12.display} over 12 months` },
  },
  {
    n: 3,
    title: "Unit economics",
    headline: "92% gross margin",
    body: "Software margins from day one.",
    claim: { text: "92% gross margin", status: "matches", truth: `${FIGURES.gmBooked.display} as booked` },
  },
  {
    n: 4,
    title: "Customers",
    headline: "Northern Comfort",
    body: "600 seats rolling out next quarter.",
    claim: { text: "600 seats", status: "forecast_as_fact", truth: "Contract not signed" },
  },
  {
    n: 5,
    title: "The ask",
    headline: "$4M · 22 months",
    body: "Runway to Series A.",
    claim: { text: "22 months runway", status: "unsupported", truth: "About 17 months on historical drivers" },
  },
];

export const SIM_FEED: Msg[] = [
  { id: "s1", kind: "founder", text: "We're at $1.3 million ARR and growing ten percent a month." },
  { id: "s2", kind: "vc", vc: "skeptic", text: "Stop there. Ten percent over which months? I get nine over the year and five lately." },
  {
    id: "s3",
    kind: "score",
    dims: dims(1, 2, 4, 3, 2),
    note: "You recovered by naming the 12-month rate, but only after the interruption. Put it on the slide.",
    claim: { status: "contradicts", text: "10% monthly growth" },
  },
  {
    id: "s4",
    kind: "slide",
    slide: 4,
    title: "Customers",
    note: "Northern Comfort reads as signed. Say “in pilot” and show the seat count as upside.",
  },
];

export const SIM_SCORES = {
  overall: 3.1,
  dims: dims(2.4, 3.0, 3.8, 3.2, 3.1),
  ledger: { matches: 4, contradicts: 1, unsupported: 1, forecast_as_fact: 1 } satisfies Record<ClaimStatus, number>,
  talkTime: "6:42",
  fillers: 14,
  slideSeconds: [38, 112, 74, 96, 82],
};
