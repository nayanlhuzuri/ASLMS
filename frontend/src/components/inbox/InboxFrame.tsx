"use client";

/**
 * The department case inbox (design portal-cases, decisions 4-8; plan §5.4; Annexure B "Case inbox"). It is read for
 * one department at a time (`?department=CODE`, sent to the API as `office`). The selector lists the departments of
 * `/inbox/counts`; a holder of `cases.view_all` may also pick any active department and then reads it as the API
 * allows (no action buttons unless the login also works there). A tab whose count is `null` in that department's
 * block is not shown (the API's rule, not the portal's).
 */
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, ErrorBanner, Loading, Notice, SelectField, Tabs } from "@/components/ui";
import { useDepartments, useInboxCounts, useMe } from "@/lib/api/hooks";
import type { InboxCounts, Me } from "@/lib/api/types";
import { can, departmentsOf } from "@/lib/can";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { INBOX_TABS, type InboxTab } from "@/lib/routes";

import { Claimed } from "./Claimed";
import { Pool } from "./Pool";
import { Recommended } from "./Recommended";
import { Transfers } from "./Transfers";

/** The tabs a counts block allows, in order. */
export function tabsFor(block: InboxCounts | null | undefined): InboxTab[] {
  if (!block) return [];
  const out: InboxTab[] = [];
  if (block.recommended_high !== null || block.recommended_medium !== null) out.push("recommended");
  if (block.claimed_active !== null) out.push("claimed");
  if (block.pool_with_hearing_7d !== null) out.push("pool");
  if (block.transfers_in_open !== null) out.push("transfers");
  return out;
}

function badge(tab: InboxTab, block: InboxCounts): number | null {
  if (tab === "recommended") return (block.recommended_high ?? 0) + (block.recommended_medium ?? 0);
  if (tab === "claimed") return block.claimed_active;
  if (tab === "transfers") return block.transfers_in_open;
  return null; // the pool: the API counts only pool cases with a hearing in 7 days
}

interface Selection {
  me: Me | undefined;
  department: string | null;
  block: InboxCounts | null | undefined;
  options: { code: string; label: string }[];
  isPending: boolean;
  error: unknown;
  refetch: () => void;
}

/** The selected department and its counts block. */
export function useInboxSelection(requested: string | undefined): Selection {
  const me = useMe();
  const own = useInboxCounts(null, !!me.data);
  const viewAll = can(me.data, "cases.view_all");
  const all = useDepartments(viewAll);
  const blocks = own.data?.departments ?? [];
  const ownCodes = blocks.map((b) => b.office_code).filter((c): c is string => !!c);
  const wanted = requested ? requested.trim().toUpperCase() : null;
  const department = wanted ?? ownCodes[0] ?? null;
  const inOwn = !!department && ownCodes.includes(department);
  const other = useInboxCounts(department, !!department && !inOwn && own.isSuccess);
  const block = inOwn
    ? blocks.find((b) => b.office_code === department)
    : department
      ? other.data?.departments[0]
      : blocks[0];
  const names = new Map((all.data?.departments ?? []).map((d) => [d.code, d.name]));
  const codes = viewAll ? [...new Set([...ownCodes, ...(all.data?.departments ?? []).map((d) => d.code)])] : ownCodes;
  const options = codes.map((code) => ({ code, label: names.get(code) ? `${code} — ${names.get(code)}` : code }));
  return {
    me: me.data,
    department,
    block,
    options,
    isPending: me.isPending || own.isPending || (!!department && !inOwn && other.isPending),
    error: me.error ?? own.error ?? (inOwn ? null : other.error),
    refetch: () => {
      void own.refetch();
      if (!inOwn) void other.refetch();
    },
  };
}

function tabHref(tab: InboxTab, department: string | null): string {
  const base = INBOX_TABS.find((t) => t.key === tab)!.href;
  return base + queryString({ department: department ?? undefined });
}

export function InboxFrame({ tab, params, children }: { tab: InboxTab; params: Params; children?: ReactNode }) {
  const router = useRouter();
  const sel = useInboxSelection(params.department);
  if (sel.isPending) return <Loading />;
  const tabs = tabsFor(sel.block);
  const mine = departmentsOf(sel.me);
  const readOnly = !!sel.department && !mine.includes(sel.department);
  const showSelector = sel.options.length > 1 || (sel.options.length === 1 && sel.department !== sel.options[0]!.code);
  return (
    <div className="stack">
      <h1>{T.inbox.title}</h1>
      <Notice>{T.inbox.notice}</Notice>
      <ErrorBanner error={sel.error} onRetry={sel.refetch} />
      {showSelector ? (
        <div style={{ maxWidth: 360 }}>
          <SelectField
            label={T.inbox.department}
            options={sel.options.map((o) => ({ value: o.code, label: o.label }))}
            placeholder={sel.department ? undefined : T.inbox.chooseDepartment}
            value={sel.department ?? ""}
            onChange={(e) => router.push(tabHref(tab, e.target.value || null))}
          />
        </div>
      ) : null}
      {readOnly ? <p className="muted">{T.inbox.readOnly}</p> : null}
      {sel.block && tabs.length > 0 ? (
        <Tabs
          label={T.inbox.tabs}
          items={tabs.map((t) => {
            const n = badge(t, sel.block!);
            const label = INBOX_TABS.find((x) => x.key === t)!.label;
            return { href: tabHref(t, sel.department), label: n === null ? label : `${label} (${formatNumber(n)})`, active: t === tab };
          })}
        />
      ) : null}
      {!sel.block ? null : tabs.includes(tab) ? (
        children ?? <InboxTabBody tab={tab} params={params} department={sel.department} />
      ) : sel.department || tab === "pool" ? (
        <EmptyState>{T.notFoundText}</EmptyState>
      ) : (
        <EmptyState>{T.inbox.noDepartmentInbox}</EmptyState>
      )}
    </div>
  );
}

function InboxTabBody({ tab, params, department }: { tab: InboxTab; params: Params; department: string | null }) {
  switch (tab) {
    case "recommended":
      return department ? <Recommended params={params} department={department} /> : null;
    case "claimed":
      return department ? <Claimed params={params} department={department} /> : null;
    case "pool":
      return <Pool params={params} department={department} />;
    case "transfers":
      return department ? <Transfers params={params} department={department} /> : null;
  }
}

/** `/inbox`: the first tab the login may read (keeping `?department`). */
export function InboxIndex({ params }: { params: Params }) {
  const router = useRouter();
  const sel = useInboxSelection(params.department);
  const first = tabsFor(sel.block)[0];
  useEffect(() => {
    if (first) router.replace(tabHref(first, params.department ? sel.department : null));
  }, [first, router, params.department, sel.department]);
  if (sel.isPending || first) return <Loading />;
  return (
    <div className="stack">
      <h1>{T.inbox.title}</h1>
      <ErrorBanner error={sel.error} onRetry={sel.refetch} />
      <EmptyState>{T.inbox.noDepartmentInbox}</EmptyState>
    </div>
  );
}
