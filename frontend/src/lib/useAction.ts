"use client";

import { useCallback, useState } from "react";

export type Outcome<T> = { ok: true; value: T } | { ok: false };

/** One user action against the API: busy while it runs, its error kept for the banner, `done` after success. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  const run = useCallback(async <T,>(work: () => Promise<T>): Promise<Outcome<T>> => {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      const value = await work();
      setDone(true);
      return { ok: true, value };
    } catch (err) {
      setError(err);
      return { ok: false };
    } finally {
      setBusy(false);
    }
  }, []);

  const reset = useCallback(() => {
    setError(null);
    setDone(false);
  }, []);

  return { run, busy, error, done, reset };
}
