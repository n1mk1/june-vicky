/**
 * Knowledge base helpers shared by the tree, the graph and the editor. The wikilink resolver mirrors
 * the API's (backend/vicky/kb/store.py): full path, path without extension, file name, then title.
 */

import type { KbNote } from "./types";

/** Where a draft (or the active) source of truth is checked and confirmed, at a step from 1 to 4. */
export function confirmHref(engagementId: string, step: 1 | 2 | 3 | 4 = 1): string {
  return `/knowledge/confirm?e=${encodeURIComponent(engagementId)}&step=${step}`;
}

export const WIKILINK = /\[\[([^[\]|#\n]+?)(?:#[^[\]|\n]*)?(?:\|([^[\]\n]*))?\]\]/g;

const stemOf = (path: string) => {
  const name = path.split("/").pop() ?? path;
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(0, dot) : name;
};

export function makeResolver(notes: Pick<KbNote, "id" | "path" | "title">[]) {
  const byPath = new Map<string, string>();
  const byStem = new Map<string, string>();
  const byName = new Map<string, string>();
  const byTitle = new Map<string, string>();
  for (const n of notes) {
    const p = n.path.toLowerCase();
    byPath.set(p, n.id);
    const noExt = p.replace(/\.[^./]+$/, "");
    if (!byStem.has(noExt)) byStem.set(noExt, n.id);
    const s = stemOf(n.path).toLowerCase();
    if (!byName.has(s)) byName.set(s, n.id);
    const t = n.title.trim().toLowerCase();
    if (!byTitle.has(t)) byTitle.set(t, n.id);
  }
  return (target: string): string | null => {
    const t = target.trim().replace(/\\/g, "/").toLowerCase();
    return byPath.get(t) ?? byStem.get(t) ?? byName.get(t.split("/").pop() ?? t) ?? byTitle.get(t) ?? null;
  };
}

/** `[[target|alias]]` → a markdown link on the `wikilink:` scheme the renderer turns into a button. */
export function wikilinksToMarkdown(md: string): string {
  // Leave fenced code alone: OCR text can contain brackets.
  return md
    .split(/(```[\s\S]*?```)/g)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(WIKILINK, (_m, target: string, alias?: string) => {
            const label = (alias ?? target).trim().replace(/([[\]])/g, "\\$1");
            return `[${label}](wikilink:${encodeURIComponent(target.trim())})`;
          }),
    )
    .join("");
}

/** RFC 4180-ish CSV parser (quoted fields, doubled quotes, newlines inside quotes). */
export function parseCsv(text: string, maxRows = 2000): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
      if (rows.length >= maxRows) return rows;
    } else field += c;
  }
  if (field || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export const FOLDER_ORDER = [
  "company",
  "financials",
  "customers",
  "product",
  "market",
  "team",
  "fundraising",
  "legal",
  "operations",
  "other",
  "inbox",
];

export function folderLabel(folder: string): string {
  if (!folder) return "Vault";
  return folder
    .split("/")
    .map((s) => (s ? s[0].toUpperCase() + s.slice(1) : s))
    .join(" / ");
}

/** "PDF · 12 pages · OCR on 3", "CSV · 48 rows", "PPTX · 14 slides · 2 charts". */
export function provenance(n: Pick<KbNote, "format" | "meta" | "kind" | "author">): string {
  const m = n.meta ?? {};
  const src = typeof m.source === "string" ? m.source : null;
  const ext = src?.split(".").pop()?.toUpperCase();
  const bits: string[] = [];
  if (ext) bits.push(ext);
  else bits.push(n.author === "ai" ? "Written by the organizer" : n.author === "founder" ? "Your note" : n.format.toUpperCase());
  if (typeof m.rows === "number") bits.push(`${m.rows.toLocaleString("en-US")} rows`);
  if (typeof m.pages === "number") bits.push(`${m.pages} page${m.pages === 1 ? "" : "s"}`);
  if (typeof m.slides === "number") bits.push(`${m.slides} slides`);
  if (typeof m.sheet === "string") bits.push(`sheet ${m.sheet}`);
  const ocrPages = Array.isArray(m.ocr_pages) ? m.ocr_pages.length : 0;
  if (ocrPages) bits.push(`OCR on ${ocrPages} page${ocrPages === 1 ? "" : "s"}`);
  if (typeof m.charts === "number" && m.charts) bits.push(`${m.charts} chart${m.charts === 1 ? "" : "s"}`);
  if (m.ocr === true) bits.push("OCR");
  return bits.join(" · ");
}
