"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage, type Query } from "./api";

export interface Loadable<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * GET a resource and keep it in state. Pass `null` as the path to skip loading (for dependent queries).
 * The request is re-issued whenever the path or query change, and on `reload()`.
 */
export function useApi<T>(path: string | null, query?: Query): Loadable<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [tick, setTick] = useState(0);
  const key = path === null ? null : `${path}|${JSON.stringify(query ?? {})}`;
  const queryRef = useRef(query);
  queryRef.current = query;

  useEffect(() => {
    if (key === null || path === null) {
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .get<T>(path, queryRef.current, ctrl.signal)
      .then((d) => {
        if (!ctrl.signal.aborted) setData(d);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted || (e instanceof DOMException && e.name === "AbortError")) return;
        setError(errorMessage(e));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Runs a mutation, tracking a busy flag. Returns true on success. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const run = useCallback(async (fn: () => Promise<unknown>): Promise<boolean> => {
    setBusy(true);
    try {
      await fn();
      return true;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, run };
}
