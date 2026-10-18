"use client";

import { createContext, useContext, type ReactNode } from "react";
import type { Engagement } from "@/lib/types";
import { useApi } from "@/lib/use-api";

interface ActiveEngagement {
  /** The confirmed engagement, `null` when none is confirmed yet, `undefined` while loading. */
  engagement: Engagement | null | undefined;
  loading: boolean;
  error: unknown;
  refresh: () => void;
}

const Ctx = createContext<ActiveEngagement | null>(null);

/** Shares `GET /engagements/active` across the app shell (status pill, pages, confirm flow). */
export function EngagementProvider({ children }: { children: ReactNode }) {
  const res = useApi<Engagement>("engagements/active");
  const none = res.status === 404;
  const value: ActiveEngagement = {
    engagement: none ? null : res.data,
    loading: res.loading,
    error: none ? undefined : res.error,
    refresh: res.reload,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useActiveEngagement(): ActiveEngagement {
  const v = useContext(Ctx);
  if (!v) throw new Error("useActiveEngagement must be used inside <EngagementProvider>");
  return v;
}
