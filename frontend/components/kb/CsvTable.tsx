"use client";

import { useMemo } from "react";
import { parseCsv } from "@/lib/kb";

const SHOWN = 500;

/** A CSV note as a table: sticky header, numbers right-aligned in mono. Shows the first 500 rows. */
export function CsvTable({ content }: { content: string }) {
  const rows = useMemo(() => parseCsv(content, SHOWN + 1), [content]);
  const total = useMemo(() => content.split("\n").filter((l) => l.trim()).length - 1, [content]);
  if (rows.length === 0) return <p className="text-[12.5px] text-ink-2">This table is empty.</p>;
  const [head, ...body] = rows;
  const numeric = (v: string) => /^[\s$£€(+-]*[\d,.]+%?\)?\s*$/.test(v);
  return (
    <div className="flex min-h-0 flex-col gap-2">
      <div className="scroll-thin min-h-0 overflow-auto rounded-[4px] border border-line">
        <table className="w-max min-w-full border-collapse text-[12px]">
          <thead className="sticky top-0 z-10 bg-surface-solid">
            <tr>
              {head.map((h, i) => (
                <th key={i} className="border-b border-line px-2.5 py-1.5 text-left font-mono text-[10.5px] font-normal uppercase tracking-[-0.04em] text-ink-2">
                  {h || " "}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.slice(0, SHOWN).map((r, i) => (
              <tr key={i} className="border-b border-line/60 last:border-0 hover:bg-surface-solid/40">
                {head.map((_, j) => (
                  <td
                    key={j}
                    className={numeric(r[j] ?? "") ? "px-2.5 py-1 text-right font-mono tabular-nums" : "px-2.5 py-1 text-ink-2"}
                  >
                    {r[j] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > SHOWN && <p className="label">Showing {SHOWN} of {total.toLocaleString("en-US")} rows. Edit shows them all.</p>}
    </div>
  );
}
