"use client";

/**
 * The Case inbox (design portal-ui-redesign, decisions 5 and 9; case-inbox-simplify, decisions 1 to 14): four tabs in
 * the owner's order — With Me, My Cases, Sent by Me and Department — each its own route, shown by `inboxTabsFor`
 * (display only; the API decides every list). Only With Me has a count: `files` of `/inbox/mine/counts`, the same
 * figure as the sidebar pill and the dashboard's "Cases with Me". `/custody/summary` is read only for a login tracking
 * a department, for the folded Tracking Summary in Department. The one-time notice of a case just sent away sits above
 * the tabs. Recommended, the Unclaimed pool and Transfers live in Case claim (`/claim/*`); the old URLs redirect
 * (`Redirects.tsx`).
 */
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Held, trackedDepartments } from "@/components/files/Held";
import { Sent } from "@/components/files/Sent";
import { DepartmentSummary, useCustodySummary } from "@/components/files/TrackingSummary";
import { Collapsible, EmptyState, ErrorBanner, Loading, PageHeader, Tabs } from "@/components/ui";
import { FlashNotice } from "@/components/workflow/common";
import { useMe, useMyCounts } from "@/lib/api/hooks";
import type { CustodySummary } from "@/lib/api/types";
import { can, tracksDepartment } from "@/lib/can";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { INBOX_TABS, inboxTabsFor, type InboxTab } from "@/lib/routes";

import { DepartmentCases, DepartmentChips } from "./DepartmentCases";
import { MyCases } from "./MyCases";
import { DepartmentSelect, useInboxSelection } from "./selection";

export function tabHref(tab: InboxTab, department?: string | null): string {
  const base = INBOX_TABS.find((t) => t.key === tab)!.href;
  return tab === "department" ? base + queryString({ department: department ?? undefined }) : base;
}

/** With Me's query (design case-inbox-simplify, decision 2): an incoming `held=me` is the default, `action=overdue` reads
 * as `overdue=true`. */
export function withMeParams(params: Params): Params {
  const out: Params = { ...params };
  if (out.held === "me") delete out.held;
  if (out.action === "overdue") {
    delete out.action;
    out.overdue = "true";
  }
  return out;
}

export function InboxFrame({ tab, params, children }: { tab: InboxTab; params: Params; children?: ReactNode }) {
  const me = useMe();
  const scoped = can(me.data, "cases.view_scope");
  const tracks = tracksDepartment(me.data);
  const counts = useMyCounts(scoped);
  const summary = useCustodySummary(tracks);
  const sel = useInboxSelection(tab === "department" ? params.department : undefined);
  if (me.isPending || sel.isPending || (scoped && counts.isPending)) return <Loading />;
  // Department: the server's whole-department rule for the selected department (or any of one's own), State-wide
  // readers, who may pick any department, and trackers (decision 8)
  const whole = can(sel.me, "cases.view_all") || sel.blocks.some((b) => b.whole_department);
  const tabs = inboxTabsFor(sel.me, { whole });
  const allowed = tabs.some((t) => t.key === tab);
  const count = (key: InboxTab): number | null => (key === "with-me" ? (counts.data?.files ?? null) : null);
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
        (children ?? <InboxBody tab={tab} params={params} counts={counts.data} sel={sel} summary={summary.data} />)
      )}
    </div>
  );
}

function InboxBody({
  tab,
  params,
  counts,
  sel,
  summary,
}: {
  tab: InboxTab;
  params: Params;
  counts: ReturnType<typeof useMyCounts>["data"];
  sel: ReturnType<typeof useInboxSelection>;
  summary: CustodySummary | undefined;
}) {
  if (tab === "with-me") return <Held tab="with-me" params={withMeParams(params)} />;
  if (tab === "mine") return <MyCases params={params} counts={counts} />;
  if (tab === "sent") return <Sent params={params} />;
  return <DepartmentTab params={params} sel={sel} summary={summary} />;
}

/**
 * Department (decisions 9, 11 and 12): `DepartmentCases` for a whole-department or State-wide reader of the selected
 * department; for a tracker of it without that sight, the tracked list (`/custody/held?scope=owned` narrowed to it);
 * the folded Tracking Summary for a tracker of the selected department.
 */
function DepartmentTab({
  params,
  sel,
  summary,
}: {
  params: Params;
  sel: ReturnType<typeof useInboxSelection>;
  summary: CustodySummary | undefined;
}) {
  const tracked = trackedDepartments(sel.me).map((d) => d.value);
  const viewAll = can(sel.me, "cases.view_all");
  // without `?department`, the first of one's own departments read whole, else the first one tracked
  const block =
    params.department || sel.block?.whole_department ? sel.block : (sel.blocks.find((b) => b.whole_department) ?? sel.block);
  const fallback = !params.department && !block?.whole_department && !viewAll ? tracked[0] : undefined;
  const department = params.department ? sel.department : (fallback ?? block?.office_code ?? sel.department);
  const select = <DepartmentSelect sel={{ ...sel, department }} hrefFor={(code) => tabHref("department", code)} />;
  const deptSummary = department ? summary?.departments.find((d) => d.code === department) : undefined;
  const tracking =
    department && tracked.includes(department) && deptSummary ? (
      <Collapsible summary={T.inbox.trackingSummary}>
        <DepartmentSummary d={deptSummary} />
      </Collapsible>
    ) : null;
  const readsWhole = !!department && (viewAll || (block?.office_code === department && !!block.whole_department));
  if (department && readsWhole && block) {
    return (
      <>
        {select}
        {tracking}
        <DepartmentCases key={department} params={params} department={department} block={block} />
      </>
    );
  }
  if (department && tracked.includes(department)) {
    return (
      <>
        {select}
        {tracking}
        <DepartmentChips params={params} elsewhere={false} />
        <Held key={department} tab="pending" params={params} department={department} />
      </>
    );
  }
  return (
    <>
      {select}
      <EmptyState>{department ? T.notFoundText : T.inbox.noDepartmentInbox}</EmptyState>
    </>
  );
}

/**
 * `/inbox` and `/cases` (design case-inbox-merge, decisions 7 and 12; case-inbox-simplify, decision 1): the first tab
 * the login may open, keeping the query string; with none, Search. With Me comes first for every case reader, so
 * `/inbox/counts` is not read here.
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
