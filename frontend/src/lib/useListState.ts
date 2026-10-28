"use client";

/**
 * A list's search and sort state (design list-search, decisions 4, 5 and 35).
 *
 * - **Search:** `q` is what is typed; `applied` is what the list uses. A server search settles 300 ms after the last
 *   keystroke (Enter applies at once) and is never applied below `minChars` (the tooltip says so); a browser search
 *   follows every keystroke through `useDeferredValue`, so typing stays smooth over a long list.
 * - **Sort:** one `{ key, dir }` or null for the list's default order; a key outside `sortKeys` (an old link) is the
 *   default, quietly.
 * - **URL mode** reads `q` (or `qKey`), `sort` and `dir` from the page's params and writes them with `router.replace`
 *   (no history entry per keystroke), dropping `offset`; Back restores both. **Local mode** keeps them in the component.
 * - `stacked` mirrors the table's card drawing (`DataTable.onStackedChange`) for the toolbar's Sort By select.
 */
import { usePathname, useRouter } from "next/navigation";
import { useDeferredValue, useEffect, useRef, useState } from "react";

import { LIST_MIN_CHARS } from "./listSearch";
import { queryString, type Params } from "./params";
import type { SortDir, SortState } from "./sort";
import { useDebounced } from "./useDebounced";

export interface ListStateOptions {
  mode: "url" | "local";
  /** `server`: sent to the API (debounced, `minChars`); `browser`: applied while typing. */
  search?: "server" | "browser";
  sortKeys?: readonly string[];
  minChars?: number;
  /** URL mode: the page's params. */
  params?: Params;
  /** URL mode: the search's key (default `q`; the View Cause List modal uses `vq`). */
  qKey?: string;
  ms?: number;
}

export interface ListState {
  q: string;
  setQ: (value: string) => void;
  applied: string;
  /** Enter: applies the typed search at once. */
  apply: () => void;
  clear: () => void;
  /** The typed search is shorter than the minimum, so it is not applied. */
  tooShort: boolean;
  sort: SortState | null;
  setSort: (next: SortState | null) => void;
  resetSort: () => void;
  stacked: boolean;
  setStacked: (stacked: boolean) => void;
}

function validSort(keys: readonly string[] | undefined, sort: string | undefined, dir: string | undefined): SortState | null {
  if (!sort || !keys || !keys.includes(sort)) return null;
  const d: SortDir | null = dir === "asc" || dir === "desc" ? dir : null;
  return d ? { key: sort, dir: d } : null;
}

export function useListState(options: ListStateOptions): ListState {
  const { mode, search = "server", sortKeys, params = {}, qKey = "q", ms = 300 } = options;
  const minChars = options.minChars ?? LIST_MIN_CHARS;
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const urlQ = mode === "url" ? (params[qKey] ?? "") : "";
  const [q, setQState] = useState(urlQ);
  const [localSort, setLocalSort] = useState<SortState | null>(null);
  const [stacked, setStacked] = useState(false);

  // Back or a link changes the address: the typed search follows it
  const written = useRef(urlQ);
  useEffect(() => {
    if (mode === "url" && urlQ !== written.current) {
      written.current = urlQ;
      setQState(urlQ);
    }
  }, [mode, urlQ]);

  const trimmed = q.trim();
  const usable = (v: string) => (v.length === 0 || v.length >= minChars ? v : "");
  const debounced = useDebounced(trimmed, ms);
  const deferred = useDeferredValue(q);
  const [forced, setForced] = useState<{ value: string; at: string } | null>(null);
  let applied: string;
  if (search === "browser") applied = deferred.trim();
  else if (forced && forced.at === trimmed) applied = forced.value;
  else applied = usable(debounced);
  const tooShort = search === "server" && trimmed.length > 0 && trimmed.length < minChars;

  function replace(updates: Params) {
    const next: Params = { ...params, ...updates };
    delete next.offset;
    router.replace(pathname + queryString(next));
  }

  // URL mode: write the settled search to the address
  useEffect(() => {
    if (mode !== "url" || applied === (params[qKey] ?? "")) return;
    written.current = applied;
    replace({ [qKey]: applied || undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, applied]);

  const sort = mode === "url" ? validSort(sortKeys, params.sort, params.dir) : localSort && sortKeys && !sortKeys.includes(localSort.key) ? null : localSort;

  function setSort(next: SortState | null) {
    if (mode === "url") replace({ sort: next?.key, dir: next?.dir });
    else setLocalSort(next);
  }

  return {
    q,
    setQ: (value: string) => {
      setForced(null);
      setQState(value);
    },
    applied,
    apply: () => setForced({ value: usable(trimmed), at: trimmed }),
    clear: () => {
      setQState("");
      setForced({ value: "", at: "" });
    },
    tooShort,
    sort,
    setSort,
    resetSort: () => setSort(null),
    stacked,
    setStacked,
  };
}
