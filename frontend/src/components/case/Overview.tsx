"use client";

/**
 * The Overview tab (design portal-cases, decision 10; Annexure B cards): Next hearing, Parties and advocates,
 * Proceedings, Custody (read-only here; row 13 adds Send and Recall), Stage, Latest order and Ownership, with a muted
 * "You see this case as: …" line from `access_basis`.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge, ErrorBanner, Loading } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useCase, useMe } from "@/lib/api/hooks";
import type { CaseDetail, HearingList, ListingList, OrderList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDate, formatDateTime, hearingBadge } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath, casePath } from "@/lib/refs";

import s from "./case.module.css";
import { fileUrl } from "./Orders";
import { OwnershipCard } from "./OwnershipCard";

function Card({ title, children, more }: { title: string; children: ReactNode; more?: ReactNode }) {
  return (
    <section className="card stack" aria-label={title}>
      <h3>{title}</h3>
      {children}
      {more}
    </section>
  );
}

function NextHearing({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  const listing = useQuery({
    queryKey: [...caseKey(caseRef), "listings", 1],
    queryFn: () => api<ListingList>(`${apiCasePath(caseRef)}/listings`, { query: { limit: 1 } }),
  });
  const next = c.status.next_hearing_date;
  const badge = hearingBadge(next);
  const last = listing.data?.items[0];
  return (
    <Card title={T.case.nextHearing}>
      {next ? (
        <>
          <div className="row">
            <strong>{formatDate(next)}</strong>
            {badge === "critical" ? <Badge tone="danger">{T.case.within48}</Badge> : null}
            {badge === "week" ? <Badge>{T.case.thisWeek}</Badge> : null}
          </div>
          {c.status.next_purpose ? <div>{c.status.next_purpose}</div> : null}
        </>
      ) : (
        <p className="muted">{T.case.noNext}</p>
      )}
      {last ? (
        <div className="muted">
          {T.inbox.listing(formatDate(last.list_date), last.court_no, last.sr_no)} · {T.case.source}: {last.source}
        </div>
      ) : null}
    </Card>
  );
}

function PartiesCard({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  const current = c.parties.filter((p) => p.is_current);
  const advocates = c.advocates.filter((a) => a.is_current);
  const pet = current.find((p) => p.role === "petitioner");
  const res = current.find((p) => p.role === "respondent");
  const advOf = (side: string) =>
    advocates
      .filter((a) => a.side === side)
      .map((a) => a.name_as_listed)
      .join(", ");
  const shown = (pet ? 1 : 0) + (res ? 1 : 0);
  const more = current.length - shown;
  return (
    <Card
      title={T.case.partiesCard}
      more={more > 0 ? <Link href={casePath(caseRef, "parties")}>{T.case.more(more)}</Link> : null}
    >
      <dl className={s.facts}>
        <div>
          <dt>{T.case.petitioner}</dt>
          <dd>
            {pet?.name ?? c.parties_as_printed.petitioner_summary ?? "—"}
            {advOf("petitioner") ? <div className="muted">{advOf("petitioner")}</div> : null}
          </dd>
        </div>
        <div>
          <dt>{T.case.respondent}</dt>
          <dd>
            {res?.name ?? c.parties_as_printed.respondent_summary ?? "—"}
            {advOf("respondent") ? <div className="muted">{advOf("respondent")}</div> : null}
          </dd>
        </div>
      </dl>
    </Card>
  );
}

function Proceedings({ caseRef }: { caseRef: string }) {
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "hearings", 5],
    queryFn: () => api<HearingList>(`${apiCasePath(caseRef)}/hearings`, { query: { limit: 5 } }),
  });
  return (
    <Card title={T.case.proceedings} more={<Link href={casePath(caseRef, "hearings")}>{T.case.allHearings}</Link>}>
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <p className="muted">{T.case.noHearings}</p>
        ) : (
          <ul className={s.cardList}>
            {list.data.items.map((h, i) => (
              <li key={i}>
                <strong>{formatDate(h.business_date ?? h.hearing_date)}</strong> {h.purpose ?? ""}
                {h.next_date ? <span className="muted"> → {formatDate(h.next_date)}</span> : null}
              </li>
            ))}
          </ul>
        )
      ) : null}
    </Card>
  );
}

function Custody({ c }: { c: CaseDetail }) {
  const k = c.custody;
  return (
    <Card title={T.case.custody}>
      {k ? (
        <dl className={s.facts}>
          <div>
            <dt>{T.case.holder}</dt>
            <dd>
              {k.holder_office ? `${k.holder_office.code} — ${k.holder_office.name}` : "—"}
              {k.holder_user ? (
                <div>
                  {k.holder_user.full_name}
                  {k.holder_user.designation ? `, ${k.holder_user.designation}` : ""}
                </div>
              ) : null}
            </dd>
          </div>
          <div>
            <dt>{T.case.pendingAction}</dt>
            <dd>{k.pending_action_label}</dd>
          </div>
          <div>
            <dt>{T.case.since}</dt>
            <dd>{formatDateTime(k.since)}</dd>
          </div>
          <div>
            <dt>{T.case.due}</dt>
            <dd>
              {formatDate(k.due_date)}
              {k.overdue ? (
                <>
                  {" "}
                  <Badge tone="danger">{T.case.overdue(k.overdue_days)}</Badge>
                </>
              ) : null}
            </dd>
          </div>
          {k.sent_by ? (
            <div>
              <dt>{T.case.sentBy}</dt>
              <dd>{[k.sent_by.name, k.sent_by.designation, k.sent_by.office_code].filter(Boolean).join(", ")}</dd>
            </div>
          ) : null}
          {k.remark ? (
            <div>
              <dt>{T.case.remark}</dt>
              <dd>{k.remark}</dd>
            </div>
          ) : null}
        </dl>
      ) : (
        <p className="muted">{T.case.noCustody}</p>
      )}
    </Card>
  );
}

function LatestOrder({ caseRef }: { caseRef: string }) {
  const me = useMe();
  const list = useQuery({
    queryKey: [...caseKey(caseRef), "orders", 1],
    queryFn: () => api<OrderList>(`${apiCasePath(caseRef)}/orders`, { query: { limit: 1 } }),
  });
  const o = list.data?.items[0];
  return (
    <Card title={T.case.latestOrder}>
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} />
      {list.data && !o ? <p className="muted">{T.case.noOrders}</p> : null}
      {o ? (
        <div className="row">
          <span>
            {formatDate(o.order_date)} · {o.kind}
          </span>
          {o.download_status === "stored" && can(me.data, "documents.view") ? (
            <a href={fileUrl(caseRef, o.id, "inline")} target="_blank" rel="noopener noreferrer">
              {T.case.view}
            </a>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}

export function Overview({ caseRef }: { caseRef: string }) {
  const query = useCase(caseRef);
  if (!query.data) return null;
  const c = query.data;
  const basis = c.access_basis.map((b) => T.case.bases[b] ?? b).join(", ");
  return (
    <div className="stack">
      <div className={s.cards}>
        <NextHearing caseRef={caseRef} c={c} />
        <PartiesCard caseRef={caseRef} c={c} />
        <Proceedings caseRef={caseRef} />
        <Custody c={c} />
        <Card title={T.case.stage}>
          {c.stage ? (
            <div>
              <strong>{c.stage.label}</strong>
              {c.stage.phase ? <span className="muted"> · {c.stage.phase}</span> : null}
            </div>
          ) : (
            <p className="muted">{T.case.noStage}</p>
          )}
        </Card>
        <LatestOrder caseRef={caseRef} />
      </div>
      <OwnershipCard caseRef={caseRef} detail={c} />
      {basis ? <p className="muted">{T.case.seenAs(basis)}</p> : null}
    </div>
  );
}
