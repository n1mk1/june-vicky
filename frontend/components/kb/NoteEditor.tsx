"use client";

import { Download, Network, StickyNote, Table2, FileText, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Segmented } from "@/components/ui/Segmented";
import { ErrorNote, Loading } from "@/components/ui/States";
import { ApiError, apiDelete, apiPut } from "@/lib/api";
import { fmtBytes, fmtDate } from "@/lib/format";
import { WIKILINK, makeResolver, provenance } from "@/lib/kb";
import type { KbKind, KbNote, KbNoteDetail } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { CsvTable } from "./CsvTable";
import { Markdown } from "./Markdown";

const AUTOSAVE_MS = 900;

export function KindIcon({ kind, className }: { kind: KbKind | "missing"; className?: string }) {
  const cls = cn("size-3.5 shrink-0", className);
  if (kind === "table") return <Table2 className={cls} strokeWidth={1.5} aria-hidden />;
  if (kind === "hub") return <Network className={cn(cls, "text-ember")} strokeWidth={1.5} aria-hidden />;
  if (kind === "note") return <StickyNote className={cls} strokeWidth={1.5} aria-hidden />;
  return <FileText className={cls} strokeWidth={1.5} aria-hidden />;
}

const linkSet = (s: string) =>
  [...s.matchAll(WIKILINK)]
    .map((m) => m[1].trim().toLowerCase())
    .sort()
    .join("|");

type SaveState = "saved" | "dirty" | "saving" | "conflict" | "error";

interface NoteEditorProps {
  id: string;
  notes: KbNote[];
  startInEdit?: boolean;
  onOpen: (id: string) => void;
  onCreate: (title: string) => void;
  /** Titles, paths or links changed: the tree and graph should reload. */
  onChanged: () => void;
  onDeleted: () => void;
  onClose: () => void;
}

/** One note: read it, edit it (autosaves), rename it, tag it, see what links to it. */
export function NoteEditor({ id, notes, startInEdit, onOpen, onCreate, onChanged, onDeleted, onClose }: NoteEditorProps) {
  const guard = useAccessGuard();
  const res = useApi<KbNoteDetail>(`kb/notes/${encodeURIComponent(id)}`);
  const { mutate } = res;
  const note = res.data;
  const [mode, setMode] = useState<"read" | "edit">(startInEdit ? "edit" : "read");
  const [draft, setDraft] = useState<string | null>(null);
  const [title, setTitle] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [save, setSave] = useState<SaveState>("saved");
  const [error, setError] = useState<string | null>(null);
  const resolve = useMemo(() => makeResolver(notes), [notes]);

  // Refs let the unmount flush and the debounce read the latest values without re-subscribing.
  const latest = useRef({ draft, version: note?.version, content: note?.content ?? "" });
  useEffect(() => {
    latest.current = { draft, version: note?.version, content: note?.content ?? "" };
  }, [draft, note?.version, note?.content]);

  const put = useCallback(
    async (body: Record<string, unknown>, opts: { reloadTree?: boolean } = {}) => {
      const v = latest.current.version;
      setSave("saving");
      setError(null);
      try {
        const next = await apiPut<KbNoteDetail>(`kb/notes/${encodeURIComponent(id)}`, { ...body, version: v });
        mutate(next);
        latest.current.version = next.version;
        latest.current.content = next.content;
        setSave("saved");
        if (opts.reloadTree) onChanged();
        return next;
      } catch (err) {
        if (guard(err)) return null;
        if (err instanceof ApiError && err.status === 409) setSave("conflict");
        else {
          setSave("error");
          setError(errorText(err));
        }
        return null;
      }
    },
    [id, mutate, guard, onChanged],
  );

  const inFlight = useRef(false);
  const again = useRef<() => void>(() => {});
  const saveContent = useCallback(async (): Promise<void> => {
    const { draft: d, content } = latest.current;
    if (d === null || d === content) {
      setDraft(null);
      setSave("saved");
      return;
    }
    if (inFlight.current) return; // the running save re-checks when it finishes
    inFlight.current = true;
    try {
      const linksChanged = linkSet(d) !== linkSet(content);
      const next = await put({ content: d }, { reloadTree: linksChanged });
      if (next) setDraft((cur) => (cur === d ? null : cur));
    } finally {
      inFlight.current = false;
    }
    // Typed more while it saved: save that too.
    const after = latest.current.draft;
    if (after !== null && after !== d) window.setTimeout(() => again.current(), AUTOSAVE_MS);
  }, [put]);
  useEffect(() => {
    again.current = () => void saveContent();
  }, [saveContent]);

  // Debounced autosave while typing.
  useEffect(() => {
    if (draft === null) return;
    const t = window.setTimeout(() => void saveContent(), AUTOSAVE_MS);
    return () => window.clearTimeout(t);
  }, [draft, saveContent]);

  // Leaving the note (or the page) with unsaved text still saves it.
  useEffect(() => {
    const flush = () => {
      const { draft: d, content, version } = latest.current;
      if (d !== null && d !== content) {
        void fetch(`/api/v1/kb/notes/${encodeURIComponent(id)}`, {
          method: "PUT",
          credentials: "same-origin",
          keepalive: true,
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ content: d, version }),
        });
      }
    };
    window.addEventListener("beforeunload", flush);
    return () => {
      window.removeEventListener("beforeunload", flush);
      flush();
    };
  }, [id]);

  if (res.loading && !note) return <Loading label="Opening the note" className="p-4" />;
  if (res.status === 404) {
    return (
      <div className="flex flex-col items-start gap-3 p-4">
        <ErrorNote message="That note doesn't exist any more." />
        <button type="button" className="text-[12px] text-ink underline underline-offset-2" onClick={onClose}>
          Close
        </button>
      </div>
    );
  }
  if (res.error && !note) return <ErrorNote className="p-4" message={errorText(res.error)} onRetry={res.reload} />;
  if (!note) return null;

  const content = draft ?? note.content;
  const shownTitle = title ?? note.title;
  const folder = note.path.includes("/") ? note.path.slice(0, note.path.lastIndexOf("/")) : "";

  const rename = async () => {
    const t = (title ?? "").trim();
    setTitle(null);
    if (!t || t === note.title) return;
    await put({ title: t, path: folder ? `${folder}/${t}` : t }, { reloadTree: true });
  };

  const setTags = (tags: string[]) => void put({ tags }, { reloadTree: true });

  const remove = async () => {
    if (!window.confirm(`Delete “${note.title}”? This can't be undone.`)) return;
    try {
      latest.current.draft = null;
      await apiDelete(`kb/notes/${encodeURIComponent(id)}`);
      onDeleted();
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    }
  };

  const status =
    save === "saving"
      ? "Saving"
      : save === "conflict"
        ? "Changed elsewhere"
        : save === "error"
          ? "Not saved"
          : draft !== null
            ? "Editing"
            : `Saved ${fmtDate(note.updated_at, true)}`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <span className="label flex min-w-0 items-center gap-1.5 truncate" title={note.path}>
          <KindIcon kind={note.kind} />
          <span className="truncate">{note.path}</span>
        </span>
        <div className="flex shrink-0 items-center gap-1.5">
          <Segmented
            label="View"
            value={mode}
            onChange={(m) => {
              if (m === "read") void saveContent();
              setMode(m);
            }}
            options={[
              { value: "read", label: "Read" },
              { value: "edit", label: "Edit" },
            ]}
          />
          {note.file && (
            <a
              href={`/api/v1/kb/files/${note.file.id}`}
              className="grid size-7 place-items-center rounded-full text-ink-2 transition-colors hover:text-ink"
              title={`Download the original (${note.file.filename.split("/").pop()}, ${fmtBytes(note.file.size)})`}
              aria-label="Download the original file"
            >
              <Download className="size-3.5" strokeWidth={1.5} />
            </a>
          )}
          <button
            type="button"
            onClick={() => void remove()}
            className="grid size-7 place-items-center rounded-full text-ink-2 transition-colors hover:text-ember"
            aria-label="Delete note"
            title="Delete note"
          >
            <Trash2 className="size-3.5" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={onClose}
            className="grid size-7 place-items-center rounded-full text-ink-2 transition-colors hover:text-ink"
            aria-label="Close note"
            title="Close"
          >
            <X className="size-4" strokeWidth={1.5} />
          </button>
        </div>
      </header>

      <div className="scroll-thin flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-4 py-4 md:px-5">
        <input
          aria-label="Note title"
          className="w-full bg-transparent font-display text-[26px] leading-none tracking-[-0.05em] text-ink outline-none placeholder:text-dim focus-visible:outline-none"
          value={shownTitle}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={() => void rename()}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") setTitle(null);
          }}
        />
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-dim">
          <span>{provenance(note)}</span>
          <span aria-hidden>·</span>
          <span className={cn(save === "conflict" || save === "error" ? "text-ember" : undefined)} role="status">
            {status}
          </span>
          {save === "conflict" && (
            <button
              type="button"
              className="text-ink underline underline-offset-2"
              onClick={() => {
                setDraft(null);
                setSave("saved");
                res.reload();
              }}
            >
              Load the latest (discards your edit)
            </button>
          )}
        </p>
        {error && <ErrorNote message={error} />}

        {note.author === "ai" && note.kind === "hub" && (
          <p className="rounded-[4px] border border-dashed border-line-strong px-3 py-2 text-[12px] text-ink-2">
            The organizer wrote this hub and rewrites it after each import. Edit it and it becomes yours: it won&apos;t be
            rewritten.
          </p>
        )}
        {note.summary && note.kind !== "hub" && (
          <p className="rounded-[4px] bg-surface-solid/50 px-3 py-2 text-[12.5px] leading-snug text-ink-2">
            <span className="label mr-2">Summary</span>
            {note.summary}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-1.5">
          {note.tags.map((t) => (
            <span key={t} className="group inline-flex items-center gap-1 rounded-[3px] border border-line px-2 py-0.5 font-mono text-[10px] text-ink-2">
              #{t}
              <button
                type="button"
                className="text-dim transition-colors hover:text-ember"
                aria-label={`Remove tag ${t}`}
                onClick={() => setTags(note.tags.filter((x) => x !== t))}
              >
                <X className="size-2.5" strokeWidth={2} />
              </button>
            </span>
          ))}
          <input
            aria-label="Add a tag"
            placeholder="+ tag"
            value={tagInput}
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && tagInput.trim()) {
                setTags([...note.tags, tagInput.trim()]);
                setTagInput("");
              }
            }}
            className="w-20 bg-transparent font-mono text-[10.5px] text-ink-2 outline-none placeholder:text-dim focus-visible:outline-none"
          />
        </div>

        {mode === "edit" ? (
          <textarea
            aria-label="Note content"
            value={content}
            spellCheck={note.format === "md"}
            onChange={(e) => {
              setDraft(e.target.value);
              setSave("dirty");
            }}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
                e.preventDefault();
                void saveContent();
              }
            }}
            className="scroll-thin min-h-[340px] w-full flex-1 resize-none rounded-[4px] border border-line bg-surface-solid/50 p-3 font-mono text-[12.5px] leading-relaxed text-ink outline-none focus:border-line-strong focus-visible:outline-none"
          />
        ) : note.format === "csv" ? (
          <CsvTable content={content} />
        ) : content.trim() ? (
          <Markdown source={content} resolve={resolve} onOpen={onOpen} onCreate={onCreate} />
        ) : (
          <button type="button" onClick={() => setMode("edit")} className="self-start text-[12.5px] text-dim underline underline-offset-2">
            Empty note. Start writing.
          </button>
        )}

        {(note.backlinks.length > 0 || note.outlinks.length > 0) && (
          <div className="mt-2 grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
            <LinkList title="Linked from" items={note.backlinks} onOpen={onOpen} onCreate={onCreate} />
            <LinkList title="Links to" items={note.outlinks} onOpen={onOpen} onCreate={onCreate} />
          </div>
        )}
      </div>
    </div>
  );
}

function LinkList({
  title,
  items,
  onOpen,
  onCreate,
}: {
  title: string;
  items: KbNoteDetail["backlinks"];
  onOpen: (id: string) => void;
  onCreate: (title: string) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="label">
        {title} · {items.length}
      </span>
      <ul className="flex flex-col gap-0.5">
        {items.map((l) => (
          <li key={(l.id ?? "") + l.title}>
            <button
              type="button"
              onClick={() => (l.id ? onOpen(l.id) : onCreate(l.title))}
              className={cn(
                "w-full truncate text-left text-[12.5px] transition-colors hover:text-ember",
                l.id ? "text-ink-2" : "text-dim italic",
              )}
              title={l.path ?? `${l.title} (not written yet)`}
            >
              {l.title}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
