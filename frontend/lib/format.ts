/**
 * Display formatting only. Values come from the API (computed by the metrics engine); these
 * helpers never derive new figures, they only turn a number and its unit into text.
 */

import { currencySymbol, DEFAULT_CURRENCY, isCurrency } from "./currency";
import type { InputRef, PointSource, Source } from "./types";

export { isCurrency };

/** Compact value for axes, tooltips and popovers: $1.29M, 9.0%, 8.0 mo, 1,204. */
export function fmtValue(value: number | null | undefined, unit?: string | null, currency?: string | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const u = (unit ?? "").toLowerCase();
  if (u === "money" || isCurrency(u)) return fmtMoney(value, isCurrency(u) ? u : (currency ?? DEFAULT_CURRENCY));
  if (u === "pct") return `${(value * 100).toFixed(Math.abs(value) < 0.1 ? 1 : 0)}%`;
  if (u === "months") return `${value.toFixed(1)} mo`;
  if (u === "x") return `${value.toFixed(2)}x`;
  if (u === "ratio") return value.toFixed(2);
  if (Math.abs(value) >= 1000) return Math.round(value).toLocaleString("en-US");
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

export function fmtMoney(value: number, currency = DEFAULT_CURRENCY): string {
  const sym = currencySymbol(currency);
  const sign = value < 0 ? "-" : "";
  const v = Math.abs(value);
  if (v >= 1_000_000) return `${sign}${sym}${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 10_000) return `${sign}${sym}${(v / 1_000).toFixed(1)}K`;
  if (v >= 1_000) return `${sign}${sym}${Math.round(v).toLocaleString("en-US")}`;
  return `${sign}${sym}${Math.round(v)}`;
}

/** Short axis label: $120K, 40%, 1.2K. */
export function fmtAxis(value: number, unit?: string | null, currency?: string | null): string {
  const u = (unit ?? "").toLowerCase();
  if (u === "pct") return `${Math.round(value * 100)}%`;
  const money = u === "money" || isCurrency(u);
  const sym = money ? currencySymbol(isCurrency(u) ? u : (currency ?? DEFAULT_CURRENCY)) : "";
  const sign = value < 0 ? "-" : "";
  const v = Math.abs(value);
  if (v >= 1_000_000) return `${sign}${sym}${+(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${sign}${sym}${+(v / 1_000).toFixed(0)}K`;
  return `${sign}${sym}${+v.toFixed(2)}`;
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
};

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
