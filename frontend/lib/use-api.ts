"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, apiGet, type ApiOptions } from "./api";

/** `/access?next=…` for the page the user is on now. */
export function accessUrl(next?: string): string {
  const here = next ?? (typeof window === "undefined" ? "/" : window.location.pathname + window.location.search);
  return `/access?next=${encodeURIComponent(here || "/")}`;
}

/**
 * Returns a handler for API errors: on 401 (no or expired access cookie) it sends the user to the
 * access gate and returns true; otherwise it returns false so the caller can show the error.
 */
export function useAccessGuard() {
  // Reads the current URL when an error arrives (not via usePathname, which would make every
  // page that loads data a runtime-only route under cacheComponents).
  const router = useRouter();
  return useCallback(
    (err: unknown): boolean => {
      if (err instanceof ApiError && err.needsAccess) {
        router.replace(accessUrl());
        return true;
      }
      return false;
    },
    [router],
  );
}

/** A readable message for any thrown value. */
export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 502) return err.detail || "The Vicky API is not reachable. It may be waking up; try again in a minute.";
    return err.detail || `Request failed (${err.status}).`;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

interface Loaded<T> {
  key: string;
  data: T | undefined;
  error: unknown;
}

export interface UseApi<T> {
  data: T | undefined;
  error: unknown;
  /** Status of the last error, e.g. 404 for "nothing yet" or 409 for a missing TruthPack. */
  status: number | null;
  loading: boolean;
  reload: () => void;
  /** Replace the data locally (after a mutation that returns the new object). */
  mutate: (next: T | ((prev: T | undefined) => T)) => void;
}

/**
 * GET `path` (relative to /api/v1) and keep the result. `path = null` skips the request.
 * 401 redirects to the access gate. Loading is derived from the request key, so effects never
 * set state synchronously.
 */
export function useApi<T>(path: string | null, query?: ApiOptions["query"]): UseApi<T> {
  const guard = useAccessGuard();
  const [nonce, setNonce] = useState(0);
  const key = path === null ? "" : `${path}?${JSON.stringify(query ?? {})}#${nonce}`;
  const [state, setState] = useState<Loaded<T>>({ key: "", data: undefined, error: undefined });

  useEffect(() => {
    if (path === null) return;
    let live = true;
    apiGet<T>(path, query ? (JSON.parse(JSON.stringify(query)) as ApiOptions["query"]) : undefined).then(
      (data) => {
        if (live) setState({ key, data, error: undefined });
      },
      (error: unknown) => {
        if (!live) return;
        if (guard(error)) return;
        setState((s) => ({ key, data: s.data, error }));
      },
    );
    return () => {
      live = false;
    };
    // `key` encodes path, query and nonce.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, guard]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const mutate = useCallback(
    (next: T | ((prev: T | undefined) => T)) =>
      setState((s) => ({
        ...s,
        error: undefined,
        data: typeof next === "function" ? (next as (prev: T | undefined) => T)(s.data) : next,
      })),
    [],
  );

  const current = state.key === key;
  const error = current ? state.error : undefined;
  return {
    data: state.data,
    error,
    status: error instanceof ApiError ? error.status : null,
    loading: path !== null && !current,
    reload,
    mutate,
  };
}
