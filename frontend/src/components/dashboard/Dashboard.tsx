"use client";

/**
 * The dashboard (design portal-ui-redesign, decision 23, on the Dashboard template; design portal-shell, decision 14;
 * plan §5.1; Annexure B). The greeting by the IST hour heads the page with at most one primary action ("Review cases
 * to claim"). `GET /dashboard` decides the views: "My work" (the headline numbers, Upcoming hearings and Needs your
 * attention from `/dashboard/me`), "Department" when it lists departments, "State" with `dashboard.state`; the
 * switch shows only with more than one view, and its choice is in the query string (`?view=`). A State-wide reader
 * without personal work opens on State. The Department and State views keep today's figures (reports-dashboards
 * decisions 9-11) as headline numbers and panels; the ticket panel stays at the top of the State view for the super
 * admin. Each view loads on its own and fails alone with a retry; a section the API returns as `null` is not shown;
 * nothing is computed in the browser beyond the greeting and the day words.
 * Design portal-ui-polish-2, decisions 44 and 45: the greeting names the person only when the account has a personal
 * name; the line under it is the primary designation and office; the date sits right of the view switch; each view
 * has a tooltip and the chosen one's sentence is the line under the switch (`aria-describedby`); a login with the State
 * view but no department sees Department disabled with its reason; opening on State says why.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useId, type ReactNode } from "react";

import { useFilters } from "@/components/inbox/common";
import { buttonClass, Collapsible, ErrorBanner, Loading, Notice, PageHeader, SegmentedSwitch } from "@/components/ui";
import { FlashNotice } from "@/components/workflow/common";
import { api } from "@/lib/api/client";
import { useLabels, useMe } from "@/lib/api/hooks";
import type { DashboardIndex, DashboardMe, DashboardState, TicketCounts } from "@/lib/api/types";
import { canAny } from "@/lib/can";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";
import { CASE_READERS, navFor } from "@/lib/routes";

import { Block, DepartmentSection, NoDashboard, PersonalExtras, StateBlock, TicketsBlock } from "./Blocks";
import { dashboardDate, greeting, greetingLine, hasPersonalWork, MyWork, personalName } from "./Headline";
import s from "./dashboard.module.css";

export { CaseRef, DepartmentBlock, HearingList, NoDashboard, StateBlock, TicketsBlock } from "./Blocks";

type View = "me" | "department" | "state";

function BlockQuery<D>({
  title,
  query,
  render,
}: {
  title: string;
  query: { data?: D; error: unknown; isPending: boolean; refetch: () => unknown };
  render: (data: D) => ReactNode;
}) {
  if (query.isPending) {
    return (
      <Block title={title}>
        <Loading />
      </Block>
    );
  }
  if (query.error || query.data === undefined) {
    return (
      <Block title={title}>
        <p>{T.dash.blockFailed}</p>
        <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
      </Block>
    );
  }
  return <>{render(query.data)}</>;
}

/** Holders of these see the ticket panel (user-memberships `GET /admin/tickets/counts`; the API scopes it). */
const TICKET_HANDLERS = ["admin.tickets", "users.propose_head"] as const;

function TicketsSection() {
  const query = useQuery({
    queryKey: ["dashboard", "tickets"],
    queryFn: () => api<TicketCounts>("/admin/tickets/counts"),
  });
  return <BlockQuery title={T.dash.tickets} query={query} render={(d) => <TicketsBlock data={d} />} />;
}

function StateSection() {
  const query = useQuery({ queryKey: ["dashboard", "state"], queryFn: () => api<DashboardState>("/dashboard/state") });
  return <BlockQuery title={T.dash.state} query={query} render={(d) => <StateBlock data={d} />} />;
}

function viewsOf(index: DashboardIndex | undefined): View[] {
  if (!index) return [];
  const out: View[] = [];
  if (index.me) out.push("me");
  if (index.departments.length > 0) out.push("department");
  if (index.state) out.push("state");
  return out;
}

export function Dashboard({ params = {} }: { params?: Params }) {
  const me = useMe();
  const labels = useLabels();
  const hintId = useId();
  const setFilters = useFilters(params);
  const readsCases = canAny(me.data, CASE_READERS);
  const index = useQuery({
    queryKey: ["dashboard", "index"],
    queryFn: () => api<DashboardIndex>("/dashboard"),
    enabled: readsCases,
  });
  const personal = useQuery({
    queryKey: ["dashboard", "me"],
    queryFn: () => api<DashboardMe>("/dashboard/me"),
    enabled: readsCases && !!index.data?.me,
  });
  if (me.isPending) return <Loading />;
  if (!me.data) return <ErrorBanner error={me.error} onRetry={() => me.refetch()} />;
  const handlesTickets = canAny(me.data, TICKET_HANDLERS);
  if (!readsCases) {
    return (
      <div className="stack">
        <PageHeader title={T.dash.title} />
        {handlesTickets ? <TicketsSection /> : null}
        <NoDashboard me={me.data} />
      </div>
    );
  }

  const views = viewsOf(index.data);
  const asked = params.view as View | undefined;
  // without a choice: My work, except a State-wide reader without personal work, who opens on State
  const waiting = !asked && views.includes("me") && views.includes("state") && personal.isPending;
  const view: View | undefined =
    asked && views.includes(asked)
      ? asked
      : views.includes("me") && !(views.includes("state") && personal.data && !hasPersonalWork(personal.data))
        ? "me"
        : views.includes("state")
          ? "state"
          : views[0];
  // the ticket panel heads the last view the login has (State for the super admin)
  const ticketsIn = views[views.length - 1];
  const claimShows = navFor(me.data).some((e) => e.key === "claim");
  const toClaim = personal.data?.headline.to_claim;
  const primary =
    claimShows && toClaim && toClaim.high + toClaim.medium > 0 ? (
      <Link href="/claim/recommended" className={buttonClass("primary")} data-variant="primary">
        {T.dash.reviewClaim}
      </Link>
    ) : null;
  const labelOfView = (v: View) => (v === "me" ? T.dash.viewMe : v === "department" ? T.dash.viewDepartment : T.dash.viewState);
  const options: { value: View; label: string; title: string; disabled?: boolean }[] = views.map((v) => ({
    value: v,
    label: labelOfView(v),
    title: T.dash.viewHints[v] ?? "",
  }));
  // decision 45: the State view without a department shows Department disabled with the reason (other views stay hidden)
  if (views.includes("state") && !views.includes("department")) {
    options.splice(views.includes("me") ? 1 : 0, 0, {
      value: "department",
      label: T.dash.viewDepartment,
      title: T.dash.departmentUnavailable,
      disabled: true,
    });
  }
  const openedOnState =
    !asked && view === "state" && views.includes("me") && !!personal.data && !hasPersonalWork(personal.data);
  const typeLabels = (labels.data?.user_types ?? []).map((t) => t.label);

  return (
    <div className="stack">
      <PageHeader title={greeting(personalName(me.data, typeLabels))} subtitle={greetingLine(me.data)} primary={primary} />
      <FlashNotice />
      {index.isPending ? <Loading /> : null}
      {index.error ? <ErrorBanner error={index.error} onRetry={() => index.refetch()} /> : null}
      <div className={s.viewRow}>
        {options.length > 1 && view ? (
          <div className={s.viewSwitch}>
            <SegmentedSwitch
              label={T.dash.views}
              options={options}
              value={view}
              describedBy={hintId}
              onChange={(v) => setFilters({ view: v === "me" ? undefined : v })}
            />
            <p id={hintId} className={s.viewHint}>
              {T.dash.viewHints[view]}
            </p>
          </div>
        ) : null}
        <span className={s.viewDate}>{dashboardDate()}</span>
      </div>
      {openedOnState ? <Notice>{T.dash.openedOnState}</Notice> : null}
      {index.data && views.length === 0 && handlesTickets ? <TicketsSection /> : null}
      {waiting ? <Loading /> : null}
      {!waiting && view ? (
        <>
          {handlesTickets && view === ticketsIn ? <TicketsSection /> : null}
          {view === "me" ? (
            <BlockQuery
              title={T.dash.personal}
              query={personal}
              render={(d) => (
                <MyWork data={d}>
                  <Collapsible summary={T.dash.moreWork}>
                    <PersonalExtras data={d} />
                  </Collapsible>
                </MyWork>
              )}
            />
          ) : null}
          {view === "department" && index.data ? <DepartmentSection departments={index.data.departments} /> : null}
          {view === "state" ? <StateSection /> : null}
        </>
      ) : null}
    </div>
  );
}
