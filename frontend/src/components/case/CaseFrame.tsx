"use client";

/**
 * The case page frame (design portal-cases, decision 10; plan §5.3; Annexure B "Case detail"): the header (status,
 * case type, case number, parties, CNR, court, registration date, owner department), the banners for provisional,
 * merged and not-yet-fetched cases, and one route per tab with the API's `counts` as badges. A case the API answers
 * 404 shows one neutral message, so the page reveals nothing. "Custody and stage" and "Alerts" are tabs of their
 * own (design portal-workflow, decision 2); Send file replaces the mock-up's "Hand over" and sits on the custody
 * card; the upload panel is on the Documents tab. The Case Assistant tab comes with row 14.
 */
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { Badge, Breadcrumb, Button, EmptyState, ErrorBanner, Loading, Notice, Tabs } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { caseKey, useCase, useMe } from "@/lib/api/hooks";
import type { CaseDetail } from "@/lib/api/types";
import { can, readsAudit } from "@/lib/can";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString } from "@/lib/params";
import { apiCasePath, casePath } from "@/lib/refs";
import { CASE_TABS } from "@/lib/routes";
import { useAction } from "@/lib/useAction";

import s from "./case.module.css";

// decision 10.15: green means done (disposed); pending and unknown are neutral, amber is kept for due soon
function statusTone(status: string) {
  return status === "disposed" ? "success" : undefined;
}

export function CaseHeader({ c }: { c: CaseDetail }) {
  const me = useMe();
  const owner = c.ownership.primary;
  const pet = c.parties_as_printed.petitioner_summary;
  const res = c.parties_as_printed.respondent_summary;
  return (
    <header className={s.header}>
      <Breadcrumb />
      <div className="row">
        <Badge tone={statusTone(c.status.status)}>{T.inbox.statuses[c.status.status] ?? c.status.status}</Badge>
        {c.identity.case_type_text ? <span className="muted">{c.identity.case_type_text}</span> : null}
      </div>
      <h1 className={`${s.caseNo} cno`}>{c.identity.case_no_text ?? c.ref_no}</h1>
      {pet || res ? (
        <p className={s.parties}>
          {pet ?? "—"} <span className="muted">{T.vs}</span> {res ?? "—"}
        </p>
      ) : null}
      <dl className={s.facts}>
        <div>
          <dt>{T.case.cnr}</dt>
          <dd className="mono">{c.identity.cnr ?? "—"}</dd>
        </div>
        <div>
          <dt>{T.case.court}</dt>
          <dd>{c.court?.name ?? c.identity.court_est_name ?? "—"}</dd>
        </div>
        <div>
          <dt>{T.case.registered}</dt>
          <dd>{formatDate(c.identity.registration_date)}</dd>
        </div>
        <div>
          <dt>{T.case.owner}</dt>
          <dd>{owner ? `${owner.office_code ?? ""}${owner.office_name ? ` — ${owner.office_name}` : ""}` : T.case.unowned}</dd>
        </div>
        <div>
          <dt>{T.case.refNo}</dt>
          <dd className="mono">{c.ref_no}</dd>
        </div>
      </dl>
      {readsAudit(me.data) ? (
        // design portal-audit-health, decision 7: audit readers only; the API re-checks
        <p>
          <Link href={`/audit${queryString({ case: c.ref_no })}`}>{T.audit.trail}</Link>
        </p>
      ) : null}
    </header>
  );
}

function FetchFromCourt({ caseRef }: { caseRef: string }) {
  const queryClient = useQueryClient();
  const action = useAction();
  async function fetchIt() {
    const out = await action.run(() => api(`${apiCasePath(caseRef)}/fetch-court`, { method: "POST" }));
    if (out.ok) await queryClient.invalidateQueries({ queryKey: caseKey(caseRef) });
  }
  return (
    <>
      <Button variant="secondary" busy={action.busy} onClick={fetchIt}>
        {T.case.fetch}
      </Button>
      <ErrorBanner error={action.error} />
    </>
  );
}

export function CaseFrame({ caseRef, children }: { caseRef: string; children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "";
  const query = useCase(caseRef);
  if (query.isPending) return <Loading />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return <EmptyState>{T.case.notFound}</EmptyState>;
  }
  if (query.error || !query.data) return <ErrorBanner error={query.error} onRetry={() => query.refetch()} />;
  const c = query.data;
  const base = casePath(caseRef);
  if (c.merged_into_ref_no) {
    return (
      <div className="stack">
        <CaseHeader c={c} />
        <Notice>
          {T.case.merged}{" "}
          <Link href={casePath(c.merged_into_ref_no)} className="mono">
            {T.case.openSurvivor(c.merged_into_ref_no)}
          </Link>
        </Notice>
      </div>
    );
  }
  return (
    <div className="stack">
      <CaseHeader c={c} />
      {c.portal.is_provisional ? <Notice>{T.case.provisional}</Notice> : null}
      {c.dossier_status !== "fetched" ? (
        <div className={s.banner} role="status">
          <span>{T.case.notFetched}</span>
          {can(me.data, "cases.search_court") ? <FetchFromCourt caseRef={caseRef} /> : null}
        </div>
      ) : null}
      <Tabs
        label={T.case.tabs}
        items={CASE_TABS.map((t) => {
          const href = t.key ? `${base}/${t.key}` : base;
          const n = t.count ? c.counts[t.count] : null;
          return {
            href,
            label: t.label,
            count: n,
            active: t.key ? pathname.endsWith(`/${t.key}`) : pathname === base || pathname === decodeURIComponent(base),
          };
        })}
      />
      {children}
    </div>
  );
}
