"use client";

import { useEffect, useState } from "react";
import { apiPost } from "@/lib/api";
import type { KbIndexStatus, KbStatus } from "@/lib/types";
import { errorText, useAccessGuard, useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const POLL_MS = 2000;

/**
 * The knowledge-base search index that Fill dashboard builds (docs/08-RAG.md §Indexing): "Building
 * search…", "Search ready · 214 notes", or "Search failed" with Retry. With `banner`, also says when
 * notes changed since the last Fill, since search shows the vault as of that Fill.
 */
export function SearchIndexStatus({ banner = false, className }: { banner?: boolean; className?: string }) {
  const guard = useAccessGuard();
  const status = useApi<KbStatus>("kb/status");
  const { reload } = status;
  const [error, setError] = useState<string | null>(null);
  const idx: KbIndexStatus | undefined = status.data?.index;

  useEffect(() => {
    if (idx?.status !== "building") return;
    const t = window.setTimeout(reload, POLL_MS);
    return () => window.clearTimeout(t);
  }, [idx, reload]);

  if (!idx) return null;
  const retry = async () => {
    setError(null);
    try {
      await apiPost("kb/index");
      reload();
    } catch (err) {
      if (!guard(err)) setError(errorText(err));
    }
  };

  return (
    <span className={cn("flex flex-col gap-1", className)} data-testid="search-index-status">
      <span className="inline-flex flex-wrap items-center gap-x-2 text-[11.5px] text-ink-2" role="status">
        {idx.status === "building" && (
          <>
            <span className="size-1.5 shrink-0 animate-[pulse-dot_1.2s_ease-in-out_infinite] rounded-full bg-ember" aria-hidden />
            Building search…
          </>
        )}
        {idx.status === "ready" && (
          <span title={idx.vectors ? "Keyword and meaning search, reranked" : "Keyword search (no Voyage key)"}>
            Search ready · {idx.notes} note{idx.notes === 1 ? "" : "s"}
          </span>
        )}
        {idx.status === "failed" && (
          <>
            <span className="text-ember">Search failed</span>
            <button type="button" onClick={() => void retry()} className="underline underline-offset-2 hover:text-ink">
              Retry
            </button>
          </>
        )}
        {idx.status === "none" && <span>Search builds when you press Fill dashboard</span>}
      </span>
      {banner && idx.status === "ready" && idx.changed_since > 0 && (
        <span className="text-[12px] text-ink-2" data-testid="search-index-stale">
          {idx.changed_since} note{idx.changed_since === 1 ? "" : "s"} changed since the last Fill. Fill dashboard again to
          update search.
        </span>
      )}
      {error && <span className="text-[12px] text-ember">{error}</span>}
    </span>
  );
}
