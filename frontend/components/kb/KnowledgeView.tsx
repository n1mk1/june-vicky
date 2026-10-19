"use client";

import { Download, FilePlus2, FolderUp, LayoutDashboard, Sparkles, Upload } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { SearchIndexStatus } from "@/components/kb/SearchIndexStatus";
import { CornerMarks, Panel } from "@/components/ui/Panel";
import { PillButton } from "@/components/ui/Pill";
import { ErrorNote, Loading } from "@/components/ui/States";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { fmtBytes } from "@/lib/format";
import { confirmHref } from "@/lib/kb";
import { useChannel, useSocketStatus, type Envelope } from "@/lib/socket";
import type { KbAutofill, KbGraph as Graph, KbImportResult, KbJob, KbNote, KbNoteDetail, KbStatus } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";
import { GraphLegend, KbGraph } from "./KbGraph";
import { NoteEditor } from "./NoteEditor";
import { NoteTree } from "./NoteTree";

const MAX_FILE = 50 * 1024 * 1024;
const BATCH_FILES = 20;
const BATCH_BYTES = 40 * 1024 * 1024;
const POLL_MS = 1500;
/** With the socket up, job events on `kb` drive the reloads; this slower poll only catches one it missed. */
const FALLBACK_POLL_MS = 10_000;
const ACCEPTS =
  "any file: spreadsheets, PDFs (scanned too), Word, PowerPoint, OpenDocument, emails, images, recordings (transcribed), HTML, JSON, text, or a zip of all of it";

interface Picked {
  file: File;
  /** Path inside the dropped folder, so the vault keeps the founder's folders. */
  path: string;
}

/** Files from a drop, walking into dropped folders. Entries are read synchronously, before any await. */
async function filesFromDrop(dt: DataTransfer): Promise<Picked[]> {
  const entries = [...dt.items]
    .filter((i) => i.kind === "file")
    .map((i) => i.webkitGetAsEntry?.())
    .filter((e): e is FileSystemEntry => !!e);
  if (entries.length === 0) return [...dt.files].map((file) => ({ file, path: file.name }));
  const out: Picked[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.name.startsWith(".")) return;
    if (entry.isFile) {
      const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
      out.push({ file, path: prefix + file.name });
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        if (batch.length === 0) break;
        for (const e of batch) await walk(e, `${prefix}${entry.name}/`);
      }
    }
  };
  for (const e of entries) await walk(e, "");
  return out;
}

const ORGANIZING = "Organizing…";

/** "Done: 5 notes." from a finished job's result. */
function jobSummary(job: KbJob): string | null {
  const r = (job.result ?? {}) as Record<string, number | string | Record<string, number | string>>;
  const org = (job.kind === "kb_ingest" ? r.organize : r) as Record<string, number | string> | undefined;
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
  if (job.kind === "kb_ingest") {
    const notes = Number(r.notes ?? 0);
    const failed = Number(r.failed ?? 0);
    return `Done: ${plural(notes, "note")}${failed ? `, ${failed} unreadable` : ""}.`;
  }
  return `Done: ${plural(Number(org?.organized ?? 0), "note")} organized.`;
}

/** Start a file download (the API answers with content-disposition: attachment). */
function download(href: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = "";
  a.click();
}

function batches(files: Picked[]): Picked[][] {
  const out: Picked[][] = [];
  let cur: Picked[] = [];
  let bytes = 0;
  for (const f of files) {
    if (cur.length && (cur.length >= BATCH_FILES || bytes + f.file.size > BATCH_BYTES)) {
      out.push(cur);
      cur = [];
      bytes = 0;
    }
    cur.push(f);
    bytes += f.file.size;
  }
  if (cur.length) out.push(cur);
  return out;
}

/**
 * The knowledge base tab: drop any files in, Vik converts them to markdown and CSV notes, files and
 * links them, and the vault shows as a tree, a graph and an editor. "Fill dashboard" builds a draft
 * source of truth from it for the founder to check; "Confirm knowledge base" (its last step) rebuilds search.
 */
export function KnowledgeView() {
  const router = useRouter();
  const params = useSearchParams();
  const guard = useAccessGuard();
  const selected = params.get("n");
  const fresh = params.get("new") === "1";

  const notes = useApi<KbNote[]>("kb/notes");
  const graph = useApi<Graph>("kb/graph");
  const status = useApi<KbStatus>("kb/status");
  const { reload: reloadNotes } = notes;
  const { reload: reloadGraph } = graph;
  const { reload: reloadStatus, mutate: setStatus } = status;

  const [query, setQuery] = useState("");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filling, setFilling] = useState(false);
  const fillTimer = useRef(0);
  // Next keeps this page alive but hidden (Activity) while the confirm page shows; "Filling" must
  // not come back with it.
  useLayoutEffect(
    () => () => {
      window.clearTimeout(fillTimer.current);
      setFilling(false);
    },
    [],
  );
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

  const refreshVault = useCallback(() => {
    reloadNotes();
    reloadGraph();
    reloadStatus();
  }, [reloadNotes, reloadGraph, reloadStatus]);

  const open = useCallback(
    (id: string, isNew = false) => router.replace(`/knowledge?n=${encodeURIComponent(id)}${isNew ? "&new=1" : ""}`, { scroll: false }),
    [router],
  );
  const close = useCallback(() => router.replace("/knowledge", { scroll: false }), [router]);

  // While an import or organize job runs, poll its status; reload the vault when it settles.
  const running = !!status.data?.running;
  const live = useSocketStatus() === "open";
  const wasRunning = useRef(false);
  useEffect(() => {
    if (!running) {
      if (wasRunning.current) {
        wasRunning.current = false;
        reloadNotes();
        reloadGraph();
      }
      return;
    }
    wasRunning.current = true;
    const t = window.setInterval(() => reloadStatus(), live ? FALLBACK_POLL_MS : POLL_MS);
    return () => window.clearInterval(t);
  }, [running, live, reloadNotes, reloadGraph, reloadStatus]);
  // Imports and organize passes report on `kb`, this tab's or another's (docs/05-BACKEND-SCHEMA.md §7). A job
  // this tab saw running reloads the vault through the effect above once the status says it settled; one that
  // started and ended unseen reloads it now.
  const onKbEvent = (e: Envelope) => {
    const { kind, status: st } = e.payload as { kind?: string; status?: string };
    if (e.type !== "job.status" || (kind !== "kb_ingest" && kind !== "kb_organize")) return;
    if (st === "running" || wasRunning.current) reloadStatus();
    else refreshVault();
  };
  useChannel("kb", onKbEvent, refreshVault);
  /** After starting a job: read the status now, so polling starts (or, if it already finished, reload). */
  const kick = async () => {
    // Retried with backoff: if this one read fails (a busy or rate-limited API), nothing else would
    // notice the job and the new notes would never appear.
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        const st = await apiGet<KbStatus>("kb/status");
        setStatus(st);
        if (!st.running) {
          reloadNotes();
          reloadGraph();
        }
        return;
      } catch (err) {
        if (guard(err)) return;
        await new Promise((r) => window.setTimeout(r, 1500 * (attempt + 1)));
      }
    }
  };

  const upload = async (picked: Picked[]) => {
    setError(null);
    setNotice(null);
    const tooBig = picked.filter((p) => p.file.size > MAX_FILE);
    const ok = picked.filter((p) => p.file.size <= MAX_FILE && p.file.size > 0);
    if (ok.length === 0) {
      setError(tooBig.length ? `Files are limited to ${fmtBytes(MAX_FILE)} each.` : "Those files are empty.");
      return;
    }
    let stored = 0;
    let dupes = 0;
    const failed: string[] = tooBig.map((p) => `${p.path} (over ${fmtBytes(MAX_FILE)})`);
    try {
      const groups = batches(ok);
      for (const [i, group] of groups.entries()) {
        setUploading(groups.length > 1 ? `Uploading ${i + 1} of ${groups.length}` : `Uploading ${ok.length} file${ok.length === 1 ? "" : "s"}`);
        const form = new FormData();
        for (const p of group) form.append("files", p.file, p.path);
        const res = await apiPost<KbImportResult>("kb/import", form);
        for (const f of res.files) {
          if (f.status === "stored") stored++;
          else if (f.status === "duplicate") dupes++;
          else failed.push(`${f.filename}${f.error ? ` (${f.error})` : ""}`);
        }
      }
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      setUploading(null);
    }
    const bits = [];
    if (stored) bits.push(`${stored} file${stored === 1 ? "" : "s"} added.`);
    if (dupes) bits.push(`${dupes} skipped (duplicate).`);
    if (failed.length) bits.push(`Couldn't read: ${failed.slice(0, 4).join(", ")}${failed.length > 4 ? "…" : ""}.`);
    setNotice(bits.join(" ") || null);
    if (stored) await kick();
  };

  // One create at a time: a double-click (or a ghost-link click) while one is in flight is ignored.
  const creatingRef = useRef(false);
  const [creating, setCreating] = useState(false);
  const newNote = async (title = "Untitled") => {
    if (creatingRef.current) return;
    creatingRef.current = true;
    setCreating(true);
    try {
      const n = await apiPost<KbNoteDetail>("kb/notes", { title, content: `# ${title}\n\n` });
      reloadNotes();
      reloadGraph();
      open(n.id, true);
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  };

  /** Delete from the vault row (confirmed in place): the same `DELETE /kb/notes/{id}` the open note uses. */
  const remove = async (n: KbNote) => {
    setError(null);
    try {
      await apiDelete(`kb/notes/${encodeURIComponent(n.id)}`);
      if (selected === n.id) close();
      refreshVault();
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    }
  };

  const organize = async () => {
    setError(null);
    try {
      await apiPost("kb/organize", { full: true });
      setNotice(ORGANIZING);
      await kick();
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    }
  };

  const fill = async () => {
    setFilling(true);
    setError(null);
    try {
      const out = await apiPost<KbAutofill>("kb/autofill");
      const href = confirmHref(out.engagement.id, 1);
      router.push(href);
      // A client navigation can be lost (another navigation wins, or the dev server restarted under
      // the page); if this view is still up, load the confirm page directly.
      fillTimer.current = window.setTimeout(() => window.location.assign(href), 5000);
    } catch (err) {
      setFilling(false);
      if (!guard(err)) setError(errorText(err));
    }
  };

  const s = status.data;
  const list = notes.data ?? [];
  const empty = notes.data !== undefined && list.length === 0;
  const lastFailed = s?.jobs[0]?.status === "failed" ? s.jobs[0] : undefined;
  const lastDone = !running && s?.jobs[0]?.status === "done" ? jobSummary(s.jobs[0]) : null;

  return (
    <div
      className="relative flex min-h-0 flex-1 flex-col gap-3"
      onDragEnter={(e) => {
        if (![...e.dataTransfer.types].includes("Files")) return;
        e.preventDefault();
        dragDepth.current += 1;
        setDragging(true);
      }}
      onDragOver={(e) => {
        if ([...e.dataTransfer.types].includes("Files")) e.preventDefault();
      }}
      onDragLeave={() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragging(false);
      }}
      onDrop={(e) => {
        if (![...e.dataTransfer.types].includes("Files")) return;
        e.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
        void filesFromDrop(e.dataTransfer).then(upload);
      }}
    >
      {/* Header: title, counts, actions */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="label">Knowledge base</span>
          <h1 className="display text-[clamp(28px,3.2vw,44px)]">Everything Vik knows.</h1>
          {s && (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-ink-2">
              <span title={`${s.files} original${s.files === 1 ? "" : "s"} (${fmtBytes(s.bytes)}) · organizer: ${s.llm ? "Gemini" : "offline rules"}`}>
                {s.notes} note{s.notes === 1 ? "" : "s"} · {s.tables} table{s.tables === 1 ? "" : "s"} · {s.documents} doc
                {s.documents === 1 ? "" : "s"}
              </span>
              {!s.ocr && <span title="tesseract isn't installed on this server">· OCR off</span>}
            </p>
          )}
          {s && <SearchIndexStatus banner key={`${s.organized_at ?? ""}-${s.notes}`} />}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PillButton label="Import" icon={<Upload className="size-3.5" strokeWidth={1.5} />} onClick={() => fileInput.current?.click()} />
          <PillButton
            label="Folder"
            icon={<FolderUp className="size-3.5" strokeWidth={1.5} />}
            onClick={() => folderInput.current?.click()}
            className="hidden sm:inline-flex"
          />
          <PillButton
            label="New note"
            icon={<FilePlus2 className="size-3.5" strokeWidth={1.5} />}
            onClick={() => void newNote()}
            disabled={creating}
          />
          <PillButton
            label="Organize"
            icon={<Sparkles className="size-3.5" strokeWidth={1.5} />}
            onClick={() => void organize()}
            disabled={running || list.length === 0}
            title="Re-file, re-tag, re-summarize and re-link every note, and rewrite the hubs"
          />
          <PillButton
            label="Export"
            icon={<Download className="size-3.5" strokeWidth={1.5} />}
            onClick={() => download("/api/v1/kb/export")}
            disabled={list.length === 0}
            title="Download the vault as a zip of markdown and CSV files (opens in Obsidian)"
          />
          <PillButton
            variant="solid"
            label={filling ? "Filling" : "Fill dashboard"}
            icon={<LayoutDashboard className="size-3.5" strokeWidth={1.5} />}
            onClick={() => void fill()}
            disabled={filling || running || list.length === 0}
            title="Autofill the profile, column mappings and facts from the knowledge base; confirming them updates search"
          />
        </div>
      </div>

      {(uploading || running || filling) && (
        <div className="relative flex items-center gap-2 overflow-hidden rounded-[3px] border border-line px-3 py-1.5 text-[12px] text-ink-2" role="status">
          <span className="size-1.5 shrink-0 animate-[pulse-dot_1.2s_ease-in-out_infinite] rounded-full bg-ember" aria-hidden />
          {filling
            ? "Filling…"
            : uploading
              ? `${uploading}…`
              : "Working…"}
          <span aria-hidden className="absolute inset-x-0 bottom-0 h-px overflow-hidden">
            <span className="block h-full w-1/3 animate-[progress-slide_1.1s_var(--ease-soft)_infinite] bg-ember" />
          </span>
        </div>
      )}
      {notice && !uploading && (
        <p className="flex items-start gap-2 text-[12px] text-ink-2">
          <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-ink-2" aria-hidden />
          <span>
            {notice === ORGANIZING ? (lastDone ?? ORGANIZING) : `${notice} ${lastDone ?? ""}`}{" "}
            <button type="button" className="text-dim underline underline-offset-2 hover:text-ink" onClick={() => setNotice(null)}>
              Dismiss
            </button>
          </span>
        </p>
      )}
      {error && <ErrorNote message={error} />}
      {lastFailed && !running && <ErrorNote message={`The last ${lastFailed.kind === "kb_ingest" ? "import" : "organize"} failed: ${lastFailed.error ?? "unknown error"}`} />}
      {s && s.failures.length > 0 && (
        <details className="text-[12px] text-ink-2">
          <summary className="cursor-pointer text-dim hover:text-ink">
            {s.failures.length} file{s.failures.length === 1 ? "" : "s"} couldn&apos;t be read
          </summary>
          <ul className="mt-1 flex flex-col gap-0.5 pl-4">
            {s.failures.map((f) => (
              <li key={f.id}>
                {f.filename}: <span className="text-dim">{f.error}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {notes.error && !notes.data ? (
        <ErrorNote message={errorText(notes.error)} onRetry={refreshVault} />
      ) : !notes.data ? (
        <Loading label="Opening the knowledge base" className="p-2" />
      ) : empty && !running ? (
        <DropHero onPick={() => fileInput.current?.click()} onFolder={() => folderInput.current?.click()} onNew={() => void newNote()} />
      ) : (
        <div
          className={cn(
            // One column below lg, and min-w-0 on each child, so a wide table scrolls inside its panel, not the page.
            "grid min-h-0 flex-1 grid-cols-1 gap-3",
            selected
              ? "lg:grid-cols-[240px_minmax(0,0.9fr)_minmax(0,1.1fr)]"
              : "lg:grid-cols-[260px_minmax(0,1fr)]",
          )}
        >
          <Panel title="Vault" className="max-h-[320px] min-w-0 lg:max-h-none" bodyClassName="min-h-0">
            <NoteTree
              notes={list}
              selected={selected}
              query={query}
              onQuery={setQuery}
              onOpen={(id) => open(id)}
              onDelete={remove}
            />
          </Panel>
          <Panel
            title="Graph"
            aside={<span className="label">{graph.data ? `${graph.data.nodes.length} nodes · ${graph.data.links.length} links` : ""}</span>}
            className="h-[380px] min-w-0 lg:h-auto"
            bodyClassName="relative flex min-h-0 flex-col"
          >
            {graph.data ? (
              <>
                <KbGraph
                  graph={graph.data}
                  selected={selected}
                  query={query}
                  onOpen={(id) => open(id)}
                  onCreate={(title) => void newNote(title)}
                  className="min-h-0 flex-1"
                />
                <GraphLegend className="border-t border-line px-4 py-2" />
              </>
            ) : (
              <Loading label="Drawing the graph" className="p-4" />
            )}
          </Panel>
          {selected && (
            <section className="glass relative min-h-[480px] min-w-0 rounded-[4px] lg:min-h-0">
              <CornerMarks />
              <NoteEditor
                key={selected}
                id={selected}
                notes={list}
                startInEdit={fresh}
                onOpen={(id) => open(id)}
                onCreate={(title) => void newNote(title)}
                onChanged={refreshVault}
                onDeleted={() => {
                  refreshVault();
                  close();
                }}
                onClose={close}
              />
            </section>
          )}
        </div>
      )}

      <input
        ref={fileInput}
        type="file"
        multiple
        className="sr-only"
        tabIndex={-1}
        aria-label="Import files"
        onChange={(e) => {
          const picked = [...(e.target.files ?? [])].map((file) => ({ file, path: file.name }));
          e.target.value = "";
          if (picked.length) void upload(picked);
        }}
      />
      <input
        ref={folderInput}
        type="file"
        multiple
        className="sr-only"
        tabIndex={-1}
        aria-label="Import a folder"
        {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
        onChange={(e) => {
          const picked = [...(e.target.files ?? [])]
            .filter((file) => !file.name.startsWith("."))
            .map((file) => ({ file, path: file.webkitRelativePath || file.name }));
          e.target.value = "";
          if (picked.length) void upload(picked);
        }}
      />

      {dragging && (
        <div className="pointer-events-none absolute inset-0 z-30 grid place-items-center rounded-[4px] border border-dashed border-ink bg-bg/70 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2 text-center">
            <Upload className="size-6 text-ink" strokeWidth={1.5} aria-hidden />
            <p className="display text-[32px]">Drop to add it to the knowledge base.</p>
            <p className="label">Files and folders · {ACCEPTS}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function DropHero({ onPick, onFolder, onNew }: { onPick: () => void; onFolder: () => void; onNew: () => void }) {
  return (
    <section className="glass relative flex min-h-[360px] flex-1 flex-col items-center justify-center gap-4 rounded-[4px] border-dashed p-8 text-center">
      <CornerMarks />
      <span className="label">Empty vault</span>
      <p className="display max-w-[16ch] text-[clamp(32px,4vw,56px)]">Dump everything here.</p>
      <p className="max-w-[58ch] text-[13.5px] leading-snug text-ink-2">
        Drop files or whole folders anywhere on this page: {ACCEPTS}. Vik turns each one into a markdown or CSV note (scanned
        pages and chart images are read with OCR, chart values come straight from the file), files it, tags it, links it to the
        rest and writes a hub for each area. Then <span className="text-ink">Fill dashboard</span> autofills your source of
        truth from it, and <span className="text-ink">Confirm knowledge base</span> updates search for every agent.
      </p>
      <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
        <PillButton variant="solid" label="Choose files" icon={<Upload className="size-3.5" strokeWidth={1.5} />} onClick={onPick} />
        <PillButton label="Choose a folder" icon={<FolderUp className="size-3.5" strokeWidth={1.5} />} onClick={onFolder} />
        <PillButton variant="ghost" label="Write a note" onClick={onNew} />
      </div>
    </section>
  );
}
