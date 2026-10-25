"use client";

/**
 * The Case inbox (design portal-ui-redesign, decisions 5 and 9; case-inbox-merge, decisions 7 to 11: the Cases list
 * folded in): six tabs in the owner's order — Working on, Sent by me, Claimed by me, Disposed, Department cases and
 * Pending action — each its own route, shown by `inboxTabsFor` (display only; the API decides every list). Counts:
 * Working on, Claimed by me and Disposed from `/inbox/mine/counts`; Pending action the sum of `held` over
 * `/custody/summary`, read only for a login tracking a department; Sent by me and Department cases none. The one-time
 * notice of a case just sent away sits above the tabs. Recommended, the Unclaimed pool and Transfers live in Case claim
 * (`/claim/*`); the old URLs redirect (`Redirects.tsx`).
 */
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Held } from "@/components/files/Held";
import { Sent } from "@/components/files/Sent";
import { useCustodySummary } from "@/components/files/TrackingSummary";
import { EmptyState, ErrorBanner, Loading, PageHeader, Tabs } from "@/components/ui";
import { FlashNotice } from "@/components/workflow/common";
import { useMe, useMyCounts } from "@/lib/api/hooks";
import { can, tracksDepartment } from "@/lib/can";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { INBOX_TABS, inboxTabsFor, type InboxTab } from "@/lib/routes";

import { DepartmentCases } from "./DepartmentCases";
import { MyCases } from "./MyCases";
import { DepartmentSelect, useInboxSelection } from "./selection";
import { WorkingOn } from "./WorkingOn";

export function tabHref(tab: InboxTab, department?: string | null): string {
  const base = INBOX_TABS.find((t) => t.key === tab)!.href;
  return tab === "department" ? base + queryString({ department: department ?? undefined }) : base;
}

export function InboxFrame({ tab, params, children }: { tab: InboxTab; params: Params; children?: ReactNode }) {
  const me = useMe();
  const scoped = can(me.data, "cases.view_scope");
  const tracks = tracksDepartment(me.data);
  const counts = useMyCounts(scoped);
  const summary = useCustodySummary(tracks);
  const sel = useInboxSelection(tab === "department" ? params.department : undefined);
  if (me.isPending || sel.isPending || (scoped && counts.isPending)) return <Loading />;
  // Department cases: shown by the server's whole-department rule for the selected department (or any of one's own)
  // and for State-wide readers, who may pick any department (question 4)
  const whole = can(sel.me, "cases.view_all") || sel.blocks.some((b) => b.whole_department);
  const tabs = inboxTabsFor(sel.me, { whole });
  const allowed = tabs.some((t) => t.key === tab);
  const count = (key: InboxTab): number | null => {
    if (key === "working" || key === "claimed" || key === "disposed") return counts.data?.[key] ?? null;
    if (key === "pending") return summary.data ? summary.data.departments.reduce((n, d) => n + d.held, 0) : null;
    return null;
  };
  return (
    <div className="stack">
      <PageHeader title={T.inbox.myTitle} subtitle={T.inbox.mySubtitle} />
      <FlashNotice />
      <ErrorBanner error={counts.error ?? sel.error} onRetry={() => (counts.refetch(), sel.refetch())} />
      {tabs.length > 0 ? (
        <Tabs
          label={T.inbox.myTabs}
          items={tabs.map((t) => ({ href: tabHref(t.key, params.department), label: t.label, active: t.key === tab, count: count(t.key) }))}
        />
      ) : null}
      {!allowed ? (
        <EmptyState>{T.notFoundText}</EmptyState>
      ) : (
        (children ?? <InboxBody tab={tab} params={params} whole={whole} counts={counts.data} sel={sel} />)
      )}
    </div>
  );
}

function InboxBody({
  tab,
  params,
  whole,
  counts,
  sel,
}: {
  tab: InboxTab;
  params: Params;
  whole: boolean;
  counts: ReturnType<typeof useMyCounts>["data"];
  sel: ReturnType<typeof useInboxSelection>;
}) {
  if (tab === "working") return <WorkingOn params={params} counts={counts} />;
  if (tab === "sent") return <Sent params={params} />;
  if (tab === "pending") return <Held tab="pending" params={params} />;
  if (tab !== "department") return <MyCases view={tab} params={params} counts={counts} />;
  // without `?department`, the first of one's own departments read whole
  const block =
    params.department || sel.block?.whole_department ? sel.block : (sel.blocks.find((b) => b.whole_department) ?? sel.block);
  const department = params.department ? sel.department : (block?.office_code ?? sel.department);
  if (!whole || !department || !block?.whole_department) {
    return (
      <>
        <DepartmentSelect sel={sel} hrefFor={(code) => tabHref("department", code)} />
        <EmptyState>{department ? T.notFoundText : T.inbox.noDepartmentInbox}</EmptyState>
      </>
    );
  }
  return (
    <>
      <DepartmentSelect sel={{ ...sel, department }} hrefFor={(code) => tabHref("department", code)} />
      <DepartmentCases key={department} params={params} department={department} block={block} />
    </>
  );
}

/**
 * `/inbox` and `/cases` (design case-inbox-merge, decisions 7 and 12): the first tab the login may open, keeping the
 * query string; with none, Search. Department cases never comes first (it needs `cases.view_scope` or `cases.view_all`,
 * which open Working on or Sent by me), so `/inbox/counts` is not read here.
 */
export function InboxIndex({ params = {} }: { params?: Params }) {
  const me = useMe();
  const router = useRouter();
  const first = inboxTabsFor(me.data)[0];
  const target = me.isPending ? null : first ? first.href + queryString(params) : "/search";
  useEffect(() => {
    if (target) router.replace(target);
  }, [target, router]);
  return <Loading />;
}
