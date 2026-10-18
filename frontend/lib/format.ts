/**
 * Display formatting only. Values come from the API (computed by the metrics engine); these
 * helpers never derive new figures, they only turn a number and its unit into text.
 */

import { currencySymbol, DEFAULT_CURRENCY, isCurrency } from "./currency";
import type { InputRef, PointSource, Source } from "./types";

export { isCurrency };

/**
 * Rounding matches the backend (`model/figures.py`): `toFixed` rounds the exact binary value half away
 * from zero, which is what the backend's Decimal ROUND_HALF_UP does, so 0.125 reads "13%" on both sides.
 * The tier is picked after rounding (999.6 → "$1,000", not "$1000"), and a value that rounds to zero
 * has no minus sign.
 */
const signed = (value: number, shown: string, text: string) => (value < 0 && Number(shown) !== 0 ? `-${text}` : text);

/** Compact value for axes, tooltips and popovers: $1.29M, 9.0%, 8.0 mo, 1,204. */
export function fmtValue(value: number | null | undefined, unit?: string | null, currency?: string | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "–";
  const u = (unit ?? "").toLowerCase();
  if (u === "money" || isCurrency(u)) return fmtMoney(value, isCurrency(u) ? u : (currency ?? DEFAULT_CURRENCY));
  const v = Math.abs(value);
  if (u === "pct") {
    const tenth = (v * 100).toFixed(1);
    const shown = Number(tenth) < 10 ? tenth : (v * 100).toFixed(0);
    return signed(value, shown, `${shown}%`);
  }
  if (u === "months" || u === "x" || u === "ratio") {
    const shown = v.toFixed(u === "months" ? 1 : 2);
    return signed(value, shown, `${shown}${u === "months" ? " mo" : u === "x" ? "x" : ""}`);
  }
  if (v >= 999.5) {
    const shown = v.toFixed(0);
    return signed(value, shown, Number(shown).toLocaleString("en-US"));
  }
  return Number.isInteger(value) ? String(value) : signed(value, v.toFixed(2), v.toFixed(2));
}

export function fmtMoney(value: number, currency = DEFAULT_CURRENCY): string {
  if (!Number.isFinite(value)) return "–";
  const sym = currencySymbol(currency);
  const v = Math.abs(value);
  const whole = v.toFixed(0);
  if (Number(whole) < 1_000) return signed(value, whole, `${sym}${whole}`);
  if (Number(whole) < 10_000) return signed(value, whole, `${sym}${Number(whole).toLocaleString("en-US")}`);
  const k = (v / 1_000).toFixed(1);
  if (Number(k) < 1_000) return signed(value, k, `${sym}${k}K`);
  const m = (v / 1_000_000).toFixed(2);
  return signed(value, m, `${sym}${m}M`);
}

/** Short axis label: $120K, $12.5K, 40%, 2.5%, 1.2K. Ticks keep the decimals they need, never rounded to a neighbour. */
export function fmtAxis(value: number, unit?: string | null, currency?: string | null): string {
  if (!Number.isFinite(value)) return "";
  const u = (unit ?? "").toLowerCase();
  const v = Math.abs(value);
  if (u === "pct") {
    const shown = +(v * 100).toFixed(1);
    return signed(value, String(shown), `${shown}%`);
  }
  const money = u === "money" || isCurrency(u);
  const sym = money ? currencySymbol(isCurrency(u) ? u : (currency ?? DEFAULT_CURRENCY)) : "";
  const units = +v.toFixed(2);
  if (units < 1_000) return signed(value, String(units), `${sym}${units}`);
  const k = +(v / 1_000).toFixed(1);
  if (k < 1_000) return signed(value, String(k), `${sym}${k}K`);
  const m = +(v / 1_000_000).toFixed(2);
  return signed(value, String(m), `${sym}${m}M`);
}

export const fmtScore = (n: number | null | undefined, digits = 1) =>
  n === null || n === undefined || Number.isNaN(n) ? "–" : n.toFixed(digits);

export function fmtDate(iso: string | null | undefined, withTime = false): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function fmtBytes(n: number): string {
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

const KIND_LABEL: Record<string, string> = {
  csv: "CSV",
  xlsx: "XLSX",
  pdf: "PDF",
  docx: "DOCX",
  md: "MD",
  pack_summary: "Pack summary",
  founder_stated: "You said",
  benchmark: "Benchmark",
  derived: "Derived",
  note: "Knowledge base",
};

/** The knowledge-base note a figure's table or document came from (Fill dashboard), if any. */
export function kbNotePath(source: Source | PointSource | Record<string, unknown> | null | undefined): string | null {
  const n = (source as { kb_note?: { path?: unknown } } | null)?.kb_note;
  return n && typeof n.path === "string" ? n.path : null;
}

/** "CSV · rows 3–26", "PDF p.4", "You said". */
export function sourceLabel(source: Source | PointSource | Record<string, unknown> | null | undefined): string {
  if (!source) return "No source";
  const s = source as Source;
  const kind = KIND_LABEL[s.kind] ?? s.kind ?? "Source";
  if (s.kind === "founder_stated") return kind;
  if (s.kind === "pdf" && s.page) return `${kind} p.${s.page}`;
  return s.ref ? `${kind} · ${s.ref}` : kind;
}

/** One input cell or figure behind a computed point. */
export function inputLabel(i: InputRef): string {
  const what = i.figure_id ?? i.field ?? i.raw ?? "input";
  const at = i.period ? ` ${i.period}` : "";
  const val = i.value !== null && i.value !== undefined ? ` = ${fmtValue(i.value)}` : "";
  return `${what}${at}${val}`;
}

export const humanize = (s: string) => s.replace(/[_.]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
