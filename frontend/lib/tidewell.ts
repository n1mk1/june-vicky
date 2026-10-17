/**
 * Tidewell sample data. Monthly actuals are transcribed from
 * backend/data/samples/tidewell/income_statement_monthly.csv; every derived figure is
 * computed here in code and carries its source. Figures the CSV can't support
 * (cash runway, retention) are labelled as the data pack summary.
 */

export type FigureKind = "historical" | "pack_summary" | "trend";

export interface Figure {
  id: string;
  label: string;
  value: number;
  display: string;
  formula: string;
  source: string;
  kind: FigureKind;
}

export interface MonthRow {
  month: string;
  subscription: number;
  services: number;
  cogs: number;
  cs: number;
  opex: number;
  srred: number;
  net: number;
}

const CSV = "CSV 01 · income statement";

export const MONTHS: MonthRow[] = [
  { month: "2024-10", subscription: 15171, services: 2400, cogs: 3582, cs: 5500, opex: 71481, srred: 0, net: -57492 },
  { month: "2024-11", subscription: 15327, services: 0, cogs: 3592, cs: 5500, opex: 71604, srred: 0, net: -59869 },
  { month: "2024-12", subscription: 16302, services: 1200, cogs: 3652, cs: 5500, opex: 72290, srred: 0, net: -58440 },
  { month: "2025-01", subscription: 18135, services: 2400, cogs: 3765, cs: 5500, opex: 80853, srred: 0, net: -64083 },
  { month: "2025-02", subscription: 19890, services: 3600, cogs: 3886, cs: 5500, opex: 91827, srred: 0, net: -72223 },
  { month: "2025-03", subscription: 20982, services: 3600, cogs: 3949, cs: 5500, opex: 98953, srred: 0, net: -78320 },
  { month: "2025-04", subscription: 24375, services: 4800, cogs: 4155, cs: 5500, opex: 103060, srred: 0, net: -78040 },
  { month: "2025-05", subscription: 27066, services: 2400, cogs: 4339, cs: 5500, opex: 102283, srred: 0, net: -77156 },
  { month: "2025-06", subscription: 30498, services: 6000, cogs: 4563, cs: 5500, opex: 103577, srred: 96400, net: 24758 },
  { month: "2025-07", subscription: 33489, services: 4800, cogs: 4739, cs: 11000, opex: 109033, srred: 0, net: -75483 },
  { month: "2025-08", subscription: 35985, services: 6000, cogs: 4889, cs: 11000, opex: 121498, srred: 0, net: -84402 },
  { month: "2025-09", subscription: 38016, services: 4800, cogs: 4997, cs: 11000, opex: 128356, srred: 0, net: -90537 },
  { month: "2025-10", subscription: 41187, services: 6000, cogs: 5178, cs: 11000, opex: 130340, srred: 0, net: -88331 },
  { month: "2025-11", subscription: 45855, services: 7200, cogs: 5437, cs: 11000, opex: 131533, srred: 0, net: -83915 },
  { month: "2025-12", subscription: 50043, services: 6000, cogs: 5675, cs: 11000, opex: 133266, srred: 0, net: -82898 },
  { month: "2026-01", subscription: 55104, services: 7200, cogs: 5982, cs: 11000, opex: 133271, srred: 0, net: -76949 },
  { month: "2026-02", subscription: 61302, services: 6000, cogs: 6338, cs: 11000, opex: 148302, srred: 0, net: -87338 },
  { month: "2026-03", subscription: 74255, services: 22200, cogs: 6872, cs: 17000, opex: 158188, srred: 0, net: -68605 },
  { month: "2026-04", subscription: 79712, services: 8400, cogs: 7187, cs: 17000, opex: 151869, srred: 0, net: -70944 },
  { month: "2026-05", subscription: 85475, services: 10800, cogs: 7501, cs: 17000, opex: 153602, srred: 0, net: -64828 },
  { month: "2026-06", subscription: 92813, services: 13200, cogs: 7917, cs: 17000, opex: 154579, srred: 0, net: -56483 },
  { month: "2026-07", subscription: 97253, services: 3600, cogs: 8172, cs: 17000, opex: 152478, srred: 182300, net: 122503 },
  { month: "2026-08", subscription: 103028, services: 10800, cogs: 8480, cs: 17000, opex: 155291, srred: 0, net: -49943 },
  { month: "2026-09", subscription: 107189, services: 7200, cogs: 8704, cs: 17000, opex: 154216, srred: 0, net: -48531 },
];

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function monthLabel(ym: string) {
  const [y, m] = ym.split("-");
  return `${MONTH_NAMES[Number(m) - 1]} ${y.slice(2)}`;
}

export function fmtMoney(n: number) {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return `$${n.toFixed(0)}`;
}

export const fmtPct = (n: number, digits = 1) => `${(n * 100).toFixed(digits)}%`;

const revenue = (r: MonthRow) => r.subscription + r.services;
const burnExSrred = (r: MonthRow) => -(r.net - r.srred);
const cmgr = (from: number, to: number, months: number) => Math.pow(to / from, 1 / months) - 1;

const last = MONTHS[MONTHS.length - 1];
const at = (offset: number) => MONTHS[MONTHS.length - 1 - offset];
const lastLabel = monthLabel(last.month);

const mrr = last.subscription;
const arr = mrr * 12;
const growth12 = cmgr(at(12).subscription, mrr, 12);
const growth2 = cmgr(at(2).subscription, mrr, 2);
const gmBooked = (revenue(last) - last.cogs) / revenue(last);
const gmWithCs = (revenue(last) - last.cogs - last.cs) / revenue(last);
const last6 = MONTHS.slice(-6);
const burn6 = last6.reduce((s, r) => s + burnExSrred(r), 0) / last6.length;

export const FIGURES = {
  arr: {
    id: "arr",
    label: "ARR",
    value: arr,
    display: fmtMoney(arr),
    formula: `${lastLabel} subscription revenue ${fmtMoney(mrr)} × 12, one-time onboarding fees excluded`,
    source: CSV,
    kind: "historical",
  },
  mrr: {
    id: "mrr",
    label: "MRR",
    value: mrr,
    display: fmtMoney(mrr),
    formula: `${lastLabel} subscription revenue`,
    source: CSV,
    kind: "historical",
  },
  growth12: {
    id: "growth12",
    label: "Monthly growth, 12 months",
    value: growth12,
    display: fmtPct(growth12),
    formula: `Compound monthly growth of subscription revenue, ${monthLabel(at(12).month)} → ${lastLabel}`,
    source: CSV,
    kind: "historical",
  },
  growth2: {
    id: "growth2",
    label: "Monthly growth, last 2 months",
    value: growth2,
    display: fmtPct(growth2),
    formula: `Compound monthly growth, ${monthLabel(at(2).month)} → ${lastLabel}`,
    source: CSV,
    kind: "historical",
  },
  gmBooked: {
    id: "gmBooked",
    label: "Gross margin, as booked",
    value: gmBooked,
    display: fmtPct(gmBooked, 0),
    formula: `(${lastLabel} revenue − COGS) ÷ revenue`,
    source: CSV,
    kind: "historical",
  },
  gmWithCs: {
    id: "gmWithCs",
    label: "Gross margin incl. customer success",
    value: gmWithCs,
    display: fmtPct(gmWithCs, 0),
    formula: `(${lastLabel} revenue − COGS − customer success salaries) ÷ revenue`,
    source: CSV,
    kind: "historical",
  },
  burn6: {
    id: "burn6",
    label: "Average monthly burn",
    value: burn6,
    display: fmtMoney(burn6),
    formula: "Net loss excluding SR&ED credits, averaged over the last 6 months",
    source: CSV,
    kind: "historical",
  },
  runway: {
    id: "runway",
    label: "Runway",
    value: 8,
    display: "8 mo",
    formula: "Cash on hand ÷ average burn. Cash isn't in CSV 01.",
    source: "Data pack summary · Appendix H",
    kind: "pack_summary",
  },
  nrr: {
    id: "nrr",
    label: "Net revenue retention",
    value: 0.88,
    display: "88%",
    formula: "Cohort data (CSV 05/06) isn't loaded yet.",
    source: "Data pack summary",
    kind: "pack_summary",
  },
} satisfies Record<string, Figure>;

export type FigureId = keyof typeof FIGURES;

export interface SeriesPoint {
  label: string;
  mrr?: number;
  trend?: number;
  burn?: number;
}

/** Actual MRR and burn, plus a dashed carry-forward of the last-2-month growth rate. Not a forecast. */
export function mrrSeries(trendMonths = 6): SeriesPoint[] {
  const points: SeriesPoint[] = MONTHS.map((r) => ({
    label: monthLabel(r.month),
    mrr: r.subscription,
    burn: burnExSrred(r),
  }));
  points[points.length - 1].trend = mrr;
  const [y, m] = last.month.split("-").map(Number);
  for (let i = 1; i <= trendMonths; i++) {
    const idx = (m - 1 + i) % 12;
    const yr = y + Math.floor((m - 1 + i) / 12);
    points.push({
      label: `${MONTH_NAMES[idx]} ${String(yr).slice(2)}`,
      trend: Math.round(mrr * Math.pow(1 + growth2, i)),
    });
  }
  return points;
}

/** The weak spots the panel will reach for first, ranked by severity. */
export const ATTACK_LIST = [
  {
    topic: "Growth is slowing",
    detail: `${FIGURES.growth12.display} a month over 12 months, ${FIGURES.growth2.display} over the last two.`,
    severity: 0.9,
  },
  {
    topic: "Runway before Series A",
    detail: `${FIGURES.runway.display} at ${FIGURES.burn6.display} a month. The plan assumes 22 months.`,
    severity: 0.85,
  },
  {
    topic: "Margin that includes support",
    detail: `${FIGURES.gmBooked.display} as booked, ${FIGURES.gmWithCs.display} once customer success is counted.`,
    severity: 0.6,
  },
];
