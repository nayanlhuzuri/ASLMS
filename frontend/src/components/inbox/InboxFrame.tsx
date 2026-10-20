"use client";

/**
 * The Case inbox = the user's own work (design portal-ui-redesign, decisions 5 and 9; plan §5.4 rearranged): Working
 * on, Files with me, Claimed by me and Disposed, with counts from `/inbox/mine/counts`, and Department cases for the
 * readers the server reads whole (`whole_department` on `/inbox/counts` for the selected department). Recommended,
 * the Unclaimed pool and Transfers live in Case claim (`/claim/*`); the old URLs redirect (`Redirects.tsx`).
 */
import type { ReactNode } from "react";

import { EmptyState, ErrorBanner, Loading, PageHeader, Tabs } from "@/components/ui";
import { useMyCounts } from "@/lib/api/hooks";
import { can } from "@/lib/can";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { INBOX_TABS, type InboxTab } from "@/lib/routes";

import { DepartmentCases } from "./DepartmentCases";
import { MyCases } from "./MyCases";
import { DepartmentSelect, useInboxSelection } from "./selection";

export function tabHref(tab: InboxTab, department?: string | null): string {
  const base = INBOX_TABS.find((t) => t.key === tab)!.href;
  return tab === "department" ? base + queryString({ department: department ?? undefined }) : base;
}

export function InboxFrame({ tab, params, children }: { tab: InboxTab; params: Params; children?: ReactNode }) {
  const counts = useMyCounts();
  const sel = useInboxSelection(tab === "department" ? params.department : undefined);
  if (counts.isPending || sel.isPending) return <Loading />;
  // Department cases: shown by the server's whole-department rule for the selected department (or any of one's own)
  // and for State-wide readers, who may pick any department (question 4)
  const whole = can(sel.me, "cases.view_all") || sel.blocks.some((b) => b.whole_department);
  const tabs = INBOX_TABS.filter((t) => t.key !== "department" || whole);
  const count = (key: InboxTab): number | null => {
    if (key === "department") return null;
    return counts.data?.[key] ?? null;
  };
  return (
    <div className="stack">
      <PageHeader title={T.inbox.myTitle} subtitle={T.inbox.mySubtitle} />
      <ErrorBanner error={counts.error ?? sel.error} onRetry={() => (counts.refetch(), sel.refetch())} />
      <Tabs
        label={T.inbox.myTabs}
        items={tabs.map((t) => ({ href: tabHref(t.key, params.department), label: t.label, active: t.key === tab, count: count(t.key) }))}
      />
      {children ?? <InboxBody tab={tab} params={params} whole={whole} counts={counts.data} sel={sel} />}
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
