"use client";

import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { ATTACH_ACCEPT } from "@/components/app/PromptBar";
import { ApiError, apiPost } from "@/lib/api";
import type { Engagement } from "@/lib/types";
import { errorText, useAccessGuard } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const MAX = 10 * 1024 * 1024;

interface UploadDropProps {
  /** Adds the file to this engagement; without it the API creates a new draft engagement. */
  engagementId?: string;
  onUploaded: (e: Engagement) => void;
  compact?: boolean;
  className?: string;
}

/** Dashed drop zone for CSV/XLSX/PDF/DOCX/MD (≤ 10 MB) → `POST /uploads`. */
export function UploadDrop({ engagementId, onUploaded, compact, className }: UploadDropProps) {
  const input = useRef<HTMLInputElement>(null);
  const guard = useAccessGuard();
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const send = async (file: File) => {
    setError(null);
    if (file.size > MAX) {
      setError("That file is over 10 MB. Split it or export only the tables you need.");
      return;
    }
    setBusy(file.name);
    try {
      const form = new FormData();
      form.append("file", file);
      if (engagementId) form.append("engagement_id", engagementId);
      onUploaded(await apiPost<Engagement>("uploads", form));
    } catch (err) {
      if (guard(err)) return;
      if (err instanceof ApiError && err.status === 413) setError("That file is over 10 MB.");
      else if (err instanceof ApiError && err.status === 415) setError("Use CSV, XLSX, PDF, DOCX or MD.");
      else setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          const f = e.dataTransfer.files?.[0];
          if (f) void send(f);
        }}
        disabled={!!busy}
        className={cn(
          "relative flex w-full flex-col items-center justify-center gap-2 overflow-hidden rounded-[4px] border border-dashed text-center transition-colors",
          compact ? "px-4 py-4" : "min-h-[180px] px-6 py-8",
          over ? "border-ink bg-surface-solid/60" : "border-line-strong hover:border-ink",
        )}
      >
        <Upload className="size-5 text-ink-2" strokeWidth={1.5} aria-hidden />
        <span className={cn("font-display tracking-[-0.03em]", compact ? "text-[15px]" : "text-[20px]")}>
          {busy ? `Reading ${busy}…` : compact ? "Add another file" : "Drop a file or click to upload"}
        </span>
        <span className="label">CSV · XLSX · PDF · DOCX · MD · up to 10 MB</span>
        {busy && (
          <span aria-hidden className="absolute inset-x-0 bottom-0 h-px overflow-hidden">
            <span className="block h-full w-1/3 bg-ember animate-[progress-slide_1.1s_var(--ease-soft)_infinite]" />
          </span>
        )}
      </button>
      <input
        ref={input}
        type="file"
        accept={ATTACH_ACCEPT}
        className="sr-only"
        tabIndex={-1}
        aria-label="Upload a file"
        onChange={(e) => {
          const f = e.target.files?.[0];
          e.target.value = "";
          if (f) void send(f);
        }}
      />
      {error && (
        <p role="alert" className="text-[12px] text-ember">
          {error}
        </p>
      )}
    </div>
  );
}
