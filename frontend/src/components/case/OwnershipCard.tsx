"use client";

/**
 * The Ownership card of the case page (design portal-cases, decisions 7, 8 and 10): the primary owner with unit,
 * officer and claimed date, the watchers, the department's own recommendation with its signals, other departments'
 * recommendations when the API returns them, the open transfer, and the action buttons. A button shows only when the
 * API's `actions` flag for it is true; the API still decides on the call. There is no "release" or "return to pool"
 * button: a claimed case never returns to the pool.
 *
 * The department that acts comes from the server (design portal-cases-followups, decisions 1, 4-6): each dialog gets
 * the action's department list from `actions`; Allot and Take over show the chosen department's own row; Suggest leaves
 * out the departments holding the case and Request transfer leaves out `transfer_from`.
 */
import { useState } from "react";

import { Badge, Button, ErrorBanner, Loading, ScoreBadge, SignalChips } from "@/components/ui";
import { OwnershipDialogs, type DialogKind } from "@/components/inbox/dialogs";
import { ApiError } from "@/lib/api/client";
import { useMe, useOwnership } from "@/lib/api/hooks";
import type { CaseDetail, Ownership } from "@/lib/api/types";
import { departmentsOf } from "@/lib/can";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import type { Signal } from "@/lib/signals";

import s from "./case.module.css";

function Row({ o }: { o: Ownership }) {
  return (
    <>
      <strong className="mono">{o.office_code ?? "—"}</strong>
      {o.unit ? <span className="mono"> · {o.unit.code}</span> : null}
      {o.officer ? <span> · {o.officer.full_name}</span> : null}
      <span className="muted"> · {T.case.claimedOn(formatDate(o.claimed_at))}</span>
    </>
  );
}

export function OwnershipCard({
  caseRef,
  detail,
  secondaryOnly = false,
}: {
  caseRef: string;
  detail: CaseDetail;
  /** Inside the Overview's folded section: the header holds the page's one primary action (design portal-ui-redesign,
   * decision 16), so every button here is secondary. */
  secondaryOnly?: boolean;
}) {
  const me = useMe();
  const view = useOwnership(caseRef);
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  if (view.isPending) return <Loading />;
  if (view.error instanceof ApiError && view.error.status === 404) {
    // the caller sees the case but not its ownership decisions: the compact owner from the overview only
    const p = detail.ownership.primary;
    return (
      <section className="card" aria-label={T.case.ownership}>
        <h3>{T.case.ownership}</h3>
        <p>{p ? `${p.office_code ?? ""}${p.office_name ? ` — ${p.office_name}` : ""}` : T.case.noOwner}</p>
      </section>
    );
  }
  if (view.error || !view.data) return <ErrorBanner error={view.error} onRetry={() => view.refetch()} />;
  const v = view.data;
  const a = v.actions;
  const mine = departmentsOf(me.data);
  const rows = [v.primary, ...v.watchers].filter((r): r is Ownership => !!r);
  const holders = rows.map((r) => r.office_code);
  const ownRecs = v.recommendations.filter((r) => r.office_code && mine.includes(r.office_code) && r.status === "recommended");
  const otherRecs = v.recommendations.filter((r) => !(r.office_code && mine.includes(r.office_code)));
  const t = v.open_transfer;
  const main = secondaryOnly ? "secondary" : "primary";
  return (
    <section className="card stack" aria-label={T.case.ownership}>
      <h3>{T.case.ownership}</h3>
      <div>
        <div className="muted">{T.case.primary}</div>
        {v.primary ? <Row o={v.primary} /> : <span>{T.case.noOwner}</span>}
      </div>
      {v.watchers.length > 0 ? (
        <div>
          <div className="muted">{T.case.watchers}</div>
          <ul className={s.cardList}>
            {v.watchers.map((w) => (
              <li key={w.id}>
                <Row o={w} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {ownRecs.map((r) => (
        <div key={r.id}>
          <div className="muted">{T.case.recommendation}</div>
          <ScoreBadge score={r.score} band={r.band} />
          <SignalChips signals={r.signals as Signal[]} />
        </div>
      ))}
      {otherRecs.length > 0 ? (
        <div>
          <div className="muted">{T.case.otherRecommendations}</div>
          <ul className={s.cardList}>
            {otherRecs.map((r) => (
              <li key={r.id}>
                <span className="mono">{r.office_code}</span> <ScoreBadge score={r.score} band={r.band} />{" "}
                <span className="muted">{r.status}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {t ? (
        <div>
          <div className="muted">{T.case.openTransfer}</div>
          <span className="mono">{t.ref_no}</span> · {T.inbox.fromTo(t.from_office_code, t.to_office_code)}{" "}
          <Badge tone="warning">{T.inbox.transferStatuses[t.status] ?? t.status}</Badge>
          {t.reason ? <div>{t.reason}</div> : null}
        </div>
      ) : null}
      <div className="row">
        {a.claim ? (
          <Button
            variant={main}
            onClick={() =>
              setDialog({
                kind: "claim",
                caseRef,
                departments: a.claim_departments ?? null,
                currentOwner: v.primary?.office_code ?? null,
              })
            }
          >
            {T.own.claim}
          </Button>
        ) : null}
        {a.dismiss ? (
          <Button variant="secondary" onClick={() => setDialog({ kind: "dismiss", caseRef, departments: a.dismiss_departments })}>
            {T.own.dismiss}
          </Button>
        ) : null}
        {a.suggest ? (
          <Button
            variant="secondary"
            onClick={() => setDialog({ kind: "suggest", caseRef, departments: a.suggest_departments, exclude: holders })}
          >
            {T.own.suggest}
          </Button>
        ) : null}
        {a.allot && a.allot_departments.length > 0 ? (
          <Button
            variant="secondary"
            onClick={() => setDialog({ kind: "allot", caseRef, departments: a.allot_departments, rows })}
          >
            {T.own.allot}
          </Button>
        ) : null}
        {a.take_over && a.take_over_departments.length > 0 ? (
          <Button
            variant="secondary"
            onClick={() => setDialog({ kind: "take_over", caseRef, departments: a.take_over_departments, rows })}
          >
            {T.own.takeOver}
          </Button>
        ) : null}
        {a.request_transfer ? (
          <Button variant="secondary" onClick={() => setDialog({ kind: "transfer", caseRef, exclude: [a.transfer_from] })}>
            {T.own.requestTransfer}
          </Button>
        ) : null}
        {a.withdraw_transfer && t ? (
          <Button variant="secondary" onClick={() => setDialog({ kind: "withdraw", caseRef, transferId: t.id })}>
            {T.own.withdraw}
          </Button>
        ) : null}
        {a.decide_transfer && t ? (
          <>
            <Button variant={main} onClick={() => setDialog({ kind: "decide", caseRef, transferId: t.id, accept: true })}>
              {T.own.accept}
            </Button>
            <Button variant="secondary" onClick={() => setDialog({ kind: "decide", caseRef, transferId: t.id, accept: false })}>
              {T.own.decline}
            </Button>
          </>
        ) : null}
        {a.stop_watching ? (
          <Button
            variant="danger"
            onClick={() => setDialog({ kind: "stop_watching", caseRef, departments: a.stop_watching_departments })}
          >
            {T.own.stopWatching}
          </Button>
        ) : null}
      </div>
      <OwnershipDialogs open={dialog} onClose={() => setDialog(null)} />
    </section>
  );
}
