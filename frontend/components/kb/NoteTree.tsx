"use client";

import { ChevronRight, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api";
import { FOLDER_ORDER, folderLabel } from "@/lib/kb";
import type { KbNote } from "@/lib/types";
import { cn } from "@/lib/utils";
import { KindIcon } from "./NoteEditor";

interface NoteTreeProps {
  notes: KbNote[];
  selected: string | null;
  query: string;
  onQuery: (q: string) => void;
  onOpen: (id: string) => void;
}

const KIND_RANK = { hub: 0, note: 1, document: 2, table: 3 } as const;

function folderRank(f: string) {
  if (!f) return -1;
  const i = FOLDER_ORDER.indexOf(f.split("/")[0]);
  return i === -1 ? FOLDER_ORDER.length : i;
}

type Hit = KbNote & { snippet?: string };

/** The vault as folders of notes, with search over titles, paths and tags, then note contents. */
export function NoteTree({ notes, selected, query, onQuery, onOpen }: NoteTreeProps) {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  const [hits, setHits] = useState<{ q: string; items: Hit[] }>({ q: "", items: [] });
  const q = query.trim().toLowerCase();

  const groups = useMemo(() => {
    const shown = q
      ? notes.filter((n) => `${n.title} ${n.path} ${n.tags.join(" ")} ${n.summary}`.toLowerCase().includes(q))
      : notes;
    const by = new Map<string, KbNote[]>();
    for (const n of shown) by.set(n.folder, [...(by.get(n.folder) ?? []), n]);
    return [...by.entries()]
      .sort(([a], [b]) => folderRank(a) - folderRank(b) || a.localeCompare(b))
      .map(([folder, items]) => ({
        folder,
        items: items.sort((a, b) => KIND_RANK[a.kind] - KIND_RANK[b.kind] || a.title.localeCompare(b.title)),
      }));
  }, [notes, q]);

  // Content search runs on the API (full text) once the query is long enough.
  useEffect(() => {
    if (q.length < 3) return;
    let live = true;
    const t = window.setTimeout(() => {
      apiGet<Hit[]>("kb/search", { q, limit: 15 }).then(
        (items) => live && setHits({ q, items }),
        () => live && setHits({ q, items: [] }),
      );
    }, 250);
    return () => {
      live = false;
      window.clearTimeout(t);
    };
  }, [q]);

  const titleHits = new Set(groups.flatMap((g) => g.items.map((n) => n.id)));
  const contentHits = q.length >= 3 && hits.q === q ? hits.items.filter((h) => !titleHits.has(h.id)) : [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <label className="relative mx-3 mt-3 block">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-dim" strokeWidth={1.5} />
        <input
          type="search"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder="Search notes"
          aria-label="Search notes"
          className="h-8 w-full rounded-[3px] border border-line bg-surface-solid/60 pr-3 pl-8 text-[12.5px] text-ink placeholder:text-dim focus:border-line-strong focus:outline-none"
        />
      </label>
      <nav aria-label="Notes" className="scroll-thin mt-2 min-h-0 flex-1 overflow-y-auto px-1.5 pb-3">
        {groups.length === 0 && contentHits.length === 0 && (
          <p className="px-3 py-4 text-[12px] text-dim">{q ? "Nothing matches." : "No notes yet."}</p>
        )}
        {groups.map(({ folder, items }) => {
          const open = q ? true : !closed.has(folder);
          return (
            <div key={folder || "root"} className="mt-1">
              <button
                type="button"
                onClick={() =>
                  setClosed((s) => {
                    const next = new Set(s);
                    if (next.has(folder)) next.delete(folder);
                    else next.add(folder);
                    return next;
                  })
                }
                aria-expanded={open}
                className="flex w-full items-center gap-1 rounded-[3px] px-1.5 py-1 text-left transition-colors hover:bg-surface-solid/50"
              >
                <ChevronRight className={cn("size-3 text-dim transition-transform", open && "rotate-90")} strokeWidth={1.5} />
                <span className="label flex-1 truncate">{folderLabel(folder)}</span>
                <span className="font-mono text-[10px] text-dim">{items.length}</span>
              </button>
              {open && (
                <ul className="ml-3 border-l border-line pl-1">
                  {items.map((n) => (
                    <li key={n.id}>
                      <button
                        type="button"
                        onClick={() => onOpen(n.id)}
                        aria-current={selected === n.id ? "page" : undefined}
                        title={n.summary || n.path}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-[3px] px-2 py-1 text-left text-[12.5px] transition-colors",
                          selected === n.id ? "bg-invert-bg text-invert-ink" : "text-ink-2 hover:bg-surface-solid/50 hover:text-ink",
                        )}
                      >
                        <KindIcon kind={n.kind} className={selected === n.id ? "text-invert-ink" : undefined} />
                        <span className="truncate">{n.title}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
        {contentHits.length > 0 && (
          <div className="mt-3 border-t border-line pt-2">
            <span className="label px-2">In note contents</span>
            <ul className="mt-1">
              {contentHits.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => onOpen(n.id)}
                    className="flex w-full flex-col gap-0.5 rounded-[3px] px-2 py-1.5 text-left transition-colors hover:bg-surface-solid/50"
                  >
                    <span className="flex items-center gap-2 text-[12.5px] text-ink">
                      <KindIcon kind={n.kind} />
                      <span className="truncate">{n.title}</span>
                    </span>
                    {n.snippet && <span className="line-clamp-2 text-[11px] text-dim">{n.snippet.replace(/\s+/g, " ")}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </nav>
    </div>
  );
}
