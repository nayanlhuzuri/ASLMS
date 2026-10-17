"use client";

/**
 * The Overview tab (design portal-cases, decision 10; Annexure B cards): Next hearing, Parties and advocates,
 * Proceedings, Custody (with Send file and Recall by the card's `can_send` / `can_recall`, design portal-workflow,
 * decisions 5-7), Stage (Set stage by `workflow.set_stage`, decision 9), Latest order and Ownership, with a muted
 * "You see this case as: …" line from `access_basis`. "Next date from orders" follows "Next hearing" and the Latest
 * order card carries the order's reading (design portal-next-dates, decision 8).
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { NextDateBlock } from "@/components/nextdates/CaseNextDate";
import { Badge, Button, ErrorBanner, Loading, Notice } from "@/components/ui";
import { CustodyActions } from "@/components/workflow/CustodyDialogs";
import { CustodyFacts } from "@/components/workflow/CustodyTab";
import { StageDialog } from "@/components/workflow/StageDialog";
import { api } from "@/lib/api/client";
import { caseKey, useCase, useMe } from "@/lib/api/hooks";
import type { CaseDetail, HearingList, ListingList, OrderList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDate, hearingBadge } from "@/lib/format";
import { T } from "@/lib/messages";
import { readingLabel } from "@/lib/nextDates";
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

function NextDateCard({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  return (
    <Card title={T.nd.card}>
      <NextDateBlock caseRef={caseRef} c={c} />
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

function Custody({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  const k = c.custody;
  return (
    <Card title={T.case.custody} more={k ? <Link href={casePath(caseRef, "custody")}>{T.wf.openCustody}</Link> : null}>
      {k ? <CustodyFacts card={k} /> : <p className="muted">{T.case.noCustody}</p>}
      {k ? <CustodyActions caseRef={caseRef} detail={c} card={k} /> : null}
    </Card>
  );
}

function StageCard({ caseRef, c }: { caseRef: string; c: CaseDetail }) {
  const [open, setOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <Card title={T.case.stage} more={c.ownership.primary ? <Link href={casePath(caseRef, "custody")}>{T.wf.openCustody}</Link> : null}>
      {notice ? <Notice>{notice}</Notice> : null}
      {c.stage ? (
        <div>
          <strong>{c.stage.label}</strong>
          {c.stage.phase ? <span className="muted"> · {c.stage.phase}</span> : null}
        </div>
      ) : (
        <p className="muted">{T.case.noStage}</p>
      )}
      {c.workflow.set_stage ? (
        <>
          <div className="row">
            <Button variant="secondary" onClick={() => setOpen(true)}>
              {T.wf.setStage}
            </Button>
          </div>
          <StageDialog
            open={open}
            caseRef={caseRef}
            current={c.stage ? { stage: c.stage.stage, response_mode: c.stage.response_mode } : null}
            onClose={() => setOpen(false)}
            onDone={setNotice}
          />
        </>
      ) : null}
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
  const reading = o ? readingLabel(o) : null;
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
      {reading ? (
        <div>
          {reading.date ? T.nd.foundInOrder(reading.date) : `${T.nd.readCol}: ${reading.words}`}
          {reading.date && o?.next_date_status === "period" ? <span className="muted"> · {reading.words}</span> : null}
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
        <NextDateCard caseRef={caseRef} c={c} />
        <PartiesCard caseRef={caseRef} c={c} />
        <Proceedings caseRef={caseRef} />
        <Custody caseRef={caseRef} c={c} />
        <StageCard caseRef={caseRef} c={c} />
        <LatestOrder caseRef={caseRef} />
      </div>
      <OwnershipCard caseRef={caseRef} detail={c} />
      {basis ? <p className="muted">{T.case.seenAs(basis)}</p> : null}
    </div>
  );
}
