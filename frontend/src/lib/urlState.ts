"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/** Page state kept in the URL query, so filters survive reloads and can be shared. */
export function useUrlState() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const get = useCallback((key: string, fallback = "") => params.get(key) ?? fallback, [params]);

  const set = useCallback(
    (patch: Record<string, string | number | boolean | null | undefined>, opts: { push?: boolean } = {}) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === undefined || v === "" || v === false) next.delete(k);
        else next.set(k, String(v));
      }
      const qs = next.toString();
      const url = qs ? `${pathname}?${qs}` : pathname;
      if (opts.push) router.push(url, { scroll: false });
      else router.replace(url, { scroll: false });
    },
    [params, pathname, router],
  );

  return { get, set, params };
}
