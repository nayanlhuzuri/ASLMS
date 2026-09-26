"use client";

import Link from "next/link";
import { apiUrl } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtScore, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { linkLabel, listTypeLabel, sourceLabel } from "@/lib/labels";
import type { CaseCard, EventOut, Hearing, LinkOut, Listing, Order, Ownership, ScoreOut } from "@/lib/types";
import { Card, CardHead } from "../../ui/Layout";
import { Pill, StatusPill } from "../../ui/Pill";
import { Async, Empty } from "../../ui/States";
import { DataTable } from "../../ui/Table";
import { caseNumber, SignalList } from "../CaseBits";
import s from "./detail.module.css";
import { eventsToEntries, Timeline } from "./Timeline";

export function HearingsTab({ caseId }: { caseId: string }) {
  const state = useApi<Hearing[]>(`/cases/${caseId}/hearings`);
  return (
    <Async state={state} loadingLabel="Loading hearings">
      {(rows) =>
        rows.length === 0 ? (
          <Empty title="No hearings recorded yet" />
        ) : (
          <DataTable
            caption="Hearings"
            rows={[...rows].sort((a, b) => b.business_date.localeCompare(a.business_date))}
            rowKey={(r, i) => `${r.business_date}-${i}`}
            columns={[
              { key: "date", header: "Date", render: (r) => fmtDate(r.business_date) },
              { key: "purpose", header: "Purpose", render: (r) => r.purpose || "-" },
              { key: "bench", header: "Bench", render: (r) => r.bench_text || "-" },
              { key: "business", header: "Business", render: (r) => r.business_text || "-" },
              { key: "next", header: "Next date", render: (r) => fmtDate(r.next_date) },
              { key: "source", header: "Source", render: (r) => sourceLabel(r.source) },
            ]}
          />
        )
      }
    </Async>
  );
}

export function OrdersTab({ caseId }: { caseId: string }) {
  const state = useApi<Order[]>(`/cases/${caseId}/orders`);
  return (
    <Async state={state} loadingLabel="Loading orders">
      {(rows) =>
        rows.length === 0 ? (
          <Empty title="No orders collected yet">Orders are downloaded from the court as they are uploaded there.</Empty>
        ) : (
          <DataTable
            caption="Orders"
            rows={[...rows].sort((a, b) => b.order_date.localeCompare(a.order_date))}
            rowKey={(r) => r.id}
            columns={[
              { key: "date", header: "Order date", render: (r) => fmtDate(r.order_date) },
              { key: "no", header: "Order no.", mono: true, render: (r) => r.order_no },
              {
                key: "kind",
                header: "Kind",
                render: (r) => (
                  <>
                    {humanize(r.kind)} {r.is_reportable ? <Pill tone="infoSoft">Reportable</Pill> : null}
                  </>
                ),
              },
              {
                key: "status",
                header: "Copy",
                render: (r) =>
                  r.document_id ? (
                    <Pill tone="success">Stored</Pill>
                  ) : (
                    <Pill tone={r.download_status === "failed" ? "criticalSoft" : "muted"}>{humanize(r.download_status)}</Pill>
                  ),
              },
              {
                key: "open",
                header: "",
                actions: true,
                render: (r) =>
                  r.document_id ? (
                    <a href={apiUrl(`/documents/${r.document_id}/download`)} target="_blank" rel="noopener" style={{ fontWeight: 600, fontSize: 14 }}>
                      View order<span className="sr-only"> dated {fmtDate(r.order_date)} (opens in a new tab)</span>
                    </a>
                  ) : null,
              },
            ]}
          />
        )
      }
    </Async>
  );
}

function LinkNode({ link }: { link: LinkOut }) {
  const body = (
    <>
      <span className={s.graphKind}>{linkLabel(link.kind)}</span>
      <span className="mono">{link.case_no || link.cnr || "Not yet in the portal"}</span>
      {link.status ? (
        <span>
          <StatusPill status={link.status} />
        </span>
      ) : null}
    </>
  );
  return link.case_id ? (
    <Link href={`/cases/${link.case_id}`} className={s.graphNode}>
      {body}
    </Link>
  ) : (
    <div className={s.graphNode}>{body}</div>
  );
}

/** Linked cases as a small relationship graph: parents on the left, this case in the middle, children right. */
export function LinksTab({ c }: { c: CaseCard }) {
  const state = useApi<LinkOut[]>(`/cases/${c.id}/links`);
  return (
    <Async state={state} loadingLabel="Loading linked cases">
      {(links) => {
        if (links.length === 0) return <Empty title="No linked cases found">Appeals, IAs and connected matters appear here when the court record or the cause list shows them.</Empty>;
        const left = links.filter((l) => l.direction === "out");
        const right = links.filter((l) => l.direction !== "out");
        return (
          <Card>
            <p className="muted" style={{ fontSize: 13 }}>
              Left: matters this case belongs to (main matter, appealed case). Right: matters that belong to this case (IAs, appeals, connected matters).
            </p>
            <div className={s.graph} role="group" aria-label="Linked cases">
              <div className={s.graphCol}>
                {left.length ? left.map((l, i) => <LinkNode key={`l${i}`} link={l} />) : <span className="muted" style={{ fontSize: 13 }}>None</span>}
              </div>
              <div className={s.graphEdge} aria-hidden="true" />
              <div className={s.graphCol}>
                <div className={`${s.graphNode} ${s.graphCentre}`}>
                  <span className={s.graphKind}>This case</span>
                  <span className="mono">{caseNumber(c)}</span>
                </div>
              </div>
              <div className={s.graphEdge} aria-hidden="true" />
              <div className={s.graphCol}>
                {right.length ? right.map((l, i) => <LinkNode key={`r${i}`} link={l} />) : <span className="muted" style={{ fontSize: 13 }}>None</span>}
              </div>
            </div>
          </Card>
        );
      }}
    </Async>
  );
}

export function TimelineTab({ caseId, trackingOnly }: { caseId: string; trackingOnly?: boolean }) {
  const state = useApi<EventOut[]>(`/cases/${caseId}/timeline`);
  return (
    <Card>
      {trackingOnly ? <CardHead title="Timeline" caption /> : null}
      <Async state={state} loadingLabel="Loading timeline">
        {(events) => (events.length === 0 ? <Empty title="No events yet" /> : <Timeline entries={eventsToEntries(events)} />)}
      </Async>
    </Card>
  );
}

export function OwnershipTab({ caseId }: { caseId: string }) {
  const state = useApi<Ownership[]>(`/cases/${caseId}/ownership`);
  return (
    <Async state={state} loadingLabel="Loading ownership history">
      {(rows) =>
        rows.length === 0 ? (
          <Empty title="No department has claimed this case">A case is held only after a department claims it.</Empty>
        ) : (
          <DataTable
            caption="Ownership history"
            rows={rows}
            rowKey={(r) => r.id}
            columns={[
              { key: "office", header: "Department", render: (r) => r.office.name },
              { key: "role", header: "Role", render: (r) => (r.role === "primary" ? "Primary owner" : "Watcher") },
              {
                key: "status",
                header: "Status",
                render: (r) => <Pill tone={r.status === "active" ? "success" : "muted"}>{humanize(r.status)}</Pill>,
              },
              {
                key: "allot",
                header: "Allotted to",
                render: (r) => {
                  const officer = r.officer as { name?: string; designation?: string | null } | null;
                  const parts = [r.unit?.name, officer?.name ? `${officer.name}${officer.designation ? `, ${officer.designation}` : ""}` : null].filter(Boolean);
                  return parts.length ? parts.join(" · ") : "-";
                },
              },
              { key: "claimed", header: "Claimed", render: (r) => `${fmtDateTime(r.claimed_at)}${r.claimed_by ? ` by ${r.claimed_by}` : ""}` },
            ]}
          />
        )
      }
    </Async>
  );
}

export function SignalsTab({ caseId }: { caseId: string }) {
  const state = useApi<ScoreOut[]>(`/cases/${caseId}/scores`);
  return (
    <Async state={state} loadingLabel="Loading scores">
      {(rows) =>
        rows.length === 0 ? (
          <Empty title="No department scored for this case">No counsel code, keyword, name pattern or watchlist entry points to a department. The case stays in the unclaimed pool.</Empty>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {[...rows]
              .sort((a, b) => b.score - a.score)
              .map((r) => (
                <Card key={r.office.office_id}>
                  <CardHead
                    title={r.office.name}
                    actions={
                      <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <span className="mono" style={{ fontSize: 18 }}>
                          {fmtScore(r.score)}
                        </span>
                        <Pill tone={r.score >= 0.85 ? "info" : r.score >= 0.5 ? "warning" : "muted"}>
                          {r.score >= 0.85 ? "Strong match" : r.score >= 0.5 ? "Possible match" : "Below threshold"}
                        </Pill>
                      </span>
                    }
                  />
                  <SignalList signals={r.signals} />
                  <div className="muted" style={{ fontSize: 12 }}>
                    Computed {fmtDateTime(r.computed_at)}. Scores only recommend; nothing is assigned until a department claims the case.
                  </div>
                </Card>
              ))}
          </div>
        )
      }
    </Async>
  );
}

export function ListingsCard({ caseId }: { caseId: string }) {
  const state = useApi<Listing[]>(`/cases/${caseId}/listings`);
  return (
    <Card>
      <CardHead title="Cause-list appearances" caption />
      <Async state={state} loadingLabel="Loading cause-list appearances">
        {(rows) =>
          rows.length === 0 ? (
            <Empty title="Not seen in a cause list yet" />
          ) : (
            <DataTable
              bare
              caption="Cause-list appearances"
              rows={[...rows].sort((a, b) => b.list_date.localeCompare(a.list_date))}
              rowKey={(r, i) => `${r.causelist_id}-${r.sr_no}-${i}`}
              columns={[
                { key: "date", header: "Date", render: (r) => fmtDate(r.list_date) },
                { key: "list", header: "List", render: (r) => `${listTypeLabel(r.list_type)} (${sourceLabel(r.source)})` },
                { key: "court", header: "Court / item", render: (r) => [r.court_no ? `Court ${r.court_no}` : null, `Item ${r.sr_no}`].filter(Boolean).join(" · ") },
                { key: "bench", header: "Bench / section", render: (r) => [r.bench, r.section].filter(Boolean).join(" · ") || "-" },
                { key: "codes", header: "Counsel codes", mono: true, render: (r) => r.counsel_codes.join("; ") || "-" },
                {
                  key: "open",
                  header: "",
                  actions: true,
                  render: (r) => (
                    <Link href={`/causelists?date=${r.list_date}&list=${r.causelist_id}`} style={{ fontSize: 14, fontWeight: 600 }}>
                      Open list
                    </Link>
                  ),
                },
              ]}
            />
          )
        }
      </Async>
    </Card>
  );
}
