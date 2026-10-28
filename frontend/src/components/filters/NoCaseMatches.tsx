"use client";

/**
 * The filter-form lists' no-match state (design list-search, decisions 1 and 18): "No cases match these filters." with
 * Clear All, instead of the list's general empty state, whenever a filter or Words is set and nothing is found. Clear
 * All keeps the list's fixed keys and its sort (decision 35: a sort is not a filter).
 */
import type { ReactNode } from "react";

import { useFilters } from "@/components/inbox/common";
import { Button } from "@/components/ui";
import { hasCaseFilter, LIST_FILTERS, type ListKey } from "@/lib/filters";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";

import s from "./filters.module.css";

/** Keys that are never cleared by Clear All: the page and the sort. */
const KEPT = new Set(["sort", "dir"]);

/** The address update of Clear All: every key but the list's fixed ones and the sort. */
export function clearAllUpdates(params: Params, list: ListKey): Params {
  const fixed = new Set<string>(LIST_FILTERS[list].fixed);
  return Object.fromEntries(Object.keys(params).filter((k) => !fixed.has(k) && !KEPT.has(k)).map((k) => [k, undefined]));
}

/** Whether a shared filter or one of the list's own filter keys is set. */
export function caseFiltersSet(params: Params, list: ListKey, ownKeys: readonly string[] = []): boolean {
  return hasCaseFilter(params, list) || ownKeys.some((k) => !!params[k]);
}

/** `children`: the list's own words when its rows are not cases ("No alerts match these filters."). */
export function NoCaseMatches({ params, list, children }: { params: Params; list: ListKey; children?: ReactNode }) {
  const setFilters = useFilters(params);
  return (
    <div className={s.noMatches} data-ui="no-matches">
      <p>{children ?? T.list.noCaseMatches}</p>
      <Button variant="secondary" size="sm" onClick={() => setFilters(clearAllUpdates(params, list))}>
        {T.filters.clearAll}
      </Button>
    </div>
  );
}
