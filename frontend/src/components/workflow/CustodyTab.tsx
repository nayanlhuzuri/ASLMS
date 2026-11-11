"use client";

/**
 * The custody card's facts (shared with the Overview) and the "Custody and stage" tab (design portal-workflow,
 * decisions 8, 9; plan §5.7): the card with Send and Recall; the movement record, paged by 50, with the remark only
 * when the API returns it; the stage block with the current stage, the history newest first, the gaps ("Not
 * recorded", guided, not enforced) and Set stage. An unclaimed case has no custody and no actions.
 *
 * Design portal-screen-fixes-work, decisions 7 and 13: the movement record reads newest first (`order=desc`, the rail's
 * and the remarks panel's order; the `#` column keeps the move numbers), the custody and stage cards have their own
 * facts grid with the remark and the note across the card's full width, offices by name only, the stage note headed
 * "Note", and the stage history rows on `ItemHead`.
 */
import { useState } from "react";

import { Badge, Button, DataTable, EmptyState, ErrorBanner, ItemHead, Loading, OfficeName, Pagination, useOfficeName, useToast } from "@/components/ui";
import { useCase, useJourney, useStages, useWorkflowCodes } from "@/lib/api/hooks";
import type { CaseDetail, CustodyCard } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { PAGE } from "@/lib/params";
import { labelFor, labelOf, serverLabel } from "@/lib/displayLabels";

import { CustodyActions } from "./CustodyDialogs";
import { StageDialog } from "./StageDialog";
import cs from "@/components/case/case.module.css";

export function CustodyFacts({ card }: { card: CustodyCard }) {
  const nameOf = useOfficeName();
  return (
    <dl className={cs.cardFacts}>
      <div>
        <dt>{T.case.holder}</dt>
        <dd>
          {card.holder_office ? <OfficeName code={card.holder_office.code} name={card.holder_office.name} /> : "—"}
          {card.holder_user ? (
            <div>
              {card.holder_user.full_name}
              {card.holder_user.designation ? `, ${card.holder_user.designation}` : ""}
            </div>
          ) : null}
        </dd>
      </div>
      <div>
        <dt>{T.case.pendingAction}</dt>
        <dd>{serverLabel(card.pending_action_label)}</dd>
      </div>
      <div>
        <dt>{T.case.since}</dt>
        <dd>{formatDateTime(card.since)}</dd>
      </div>
      <div>
        <dt>{T.case.due}</dt>
        <dd>
          {formatDate(card.due_date)}
          {card.overdue ? (
            <>
              {" "}
              <Badge tone="danger">{T.case.overdue(card.overdue_days)}</Badge>
            </>
          ) : null}
        </dd>
      </div>
      {card.sent_by ? (
        <div>
          <dt>{T.case.sentBy}</dt>
          <dd>{[card.sent_by.name, card.sent_by.designation, card.sent_by.office_code ? nameOf(card.sent_by.office_code) : null].filter(Boolean).join(", ")}</dd>
        </div>
      ) : null}
      {card.remark ? (
        <div className={cs.wide}>
          <dt>{T.case.remark}</dt>
          <dd>{card.remark}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function Movement({ caseRef, detail }: { caseRef: string; detail: CaseDetail }) {
  const nameOf = useOfficeName();
  const [offset, setOffset] = useState(0);
  // newest first: the current move leads page 1, under the card that shows where the file is now
  const history = useJourney(caseRef, PAGE, offset);
  if (history.isPending) return <Loading />;
  if (history.error || !history.data) return <ErrorBanner error={history.error} onRetry={() => history.refetch()} />;
  const { card, legs, total } = history.data;
  return (
    <>
      <section className="card stack" aria-label={T.case.custody}>
        <h2>{T.case.custody}</h2>
        {card ? <CustodyFacts card={card} /> : <p className="muted">{T.case.noCustody}</p>}
        {card ? <CustodyActions caseRef={caseRef} detail={detail} card={card} /> : null}
      </section>
      <section aria-label={T.wf.movement} className="stack">
        <h2>{T.wf.movement}</h2>
        {legs.length === 0 ? (
          <EmptyState title={T.wf.noLegsTitle}>{T.wf.noLegs}</EmptyState>
        ) : (
          <>
            <DataTable
              caption={T.wf.movement}
              rows={legs}
              rowKey={(leg) => String(leg.seq_no)}
              columns={[
                { key: "seq", header: T.wf.seq, align: "right", cell: (leg) => <span className="mono">{leg.seq_no}</span> },
                {
                  key: "holder",
                  header: T.wf.holderCol,
                  primary: true,
                  cell: (leg) => (
                    <>
                      <OfficeName code={leg.holder_office.code} name={leg.holder_office.name} />
                      {leg.holder_user ? (
                        <div>
                          {leg.holder_user.full_name}
                          {leg.holder_designation ? `, ${leg.holder_designation}` : ""}
                        </div>
                      ) : null}
                    </>
                  ),
                },
                { key: "reason", header: T.wf.reason, cell: (leg) => serverLabel(leg.reason_label) },
                { key: "action", header: T.case.pendingAction, cell: (leg) => serverLabel(leg.pending_action_label) },
                { key: "due", header: T.case.due, cell: (leg) => formatDate(leg.due_date) },
                { key: "started", header: T.wf.started, cell: (leg) => formatDateTime(leg.started_at) },
                {
                  key: "by",
                  header: T.wf.sentByCol,
                  cell: (leg) => [leg.actor_name, leg.actor_designation, leg.actor_office_code ? nameOf(leg.actor_office_code) : null].filter(Boolean).join(", ") || "—",
                },
                { key: "remark", header: T.wf.remarkCol, cell: (leg) => leg.remark ?? <span className="muted">{T.wf.notShown}</span> },
              ]}
            />
            <Pagination offset={offset} limit={PAGE} total={total} onChange={setOffset} />
          </>
        )}
      </section>
    </>
  );
}

function StageBlock({ caseRef, detail }: { caseRef: string; detail: CaseDetail }) {
  const stages = useStages(caseRef);
  const codes = useWorkflowCodes();
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const nameOf = useOfficeName();
  const stageLabel = (code: string) => labelOf(codes.data?.stages, code);
  const data = stages.data;
  const cur = data?.current ?? null;
  return (
    <section className="card stack" aria-label={T.wf.stageBlock}>
      <h2>{T.wf.stageBlock}</h2>
      {stages.isPending ? <Loading /> : null}
      <ErrorBanner error={stages.error} onRetry={() => stages.refetch()} />
      {data ? (
        <>
          {cur ? (
            <dl className={cs.cardFacts}>
              <div>
                <dt>{T.wf.currentStage}</dt>
                <dd>
                  <strong>{serverLabel(cur.label)}</strong>
                  {cur.phase ? <span className="muted"> · {cur.phase}</span> : null}
                </dd>
              </div>
              <div>
                <dt>{T.wf.responseMode}</dt>
                <dd>{serverLabel(cur.response_mode_label) ?? labelFor(undefined, cur.response_mode)}</dd>
              </div>
              <div>
                <dt>{T.wf.setBy}</dt>
                <dd>
                  {[cur.set_by, cur.office_code ? nameOf(cur.office_code) : null].filter(Boolean).join(", ") || "—"} · {formatDateTime(cur.set_at)}
                </dd>
              </div>
              {cur.note ? (
                <div className={cs.wide}>
                  <dt>{T.wf.stageNoteHead}</dt>
                  <dd>{cur.note}</dd>
                </div>
              ) : null}
            </dl>
          ) : (
            <p className="muted">{T.case.noStage}</p>
          )}
          {data.gaps.length > 0 ? <p className="muted">{T.wf.notRecorded(data.gaps.map(stageLabel).join(", "))}</p> : null}
          <h3>{T.wf.stageHistory}</h3>
          {data.history.length === 0 ? (
            <EmptyState compact>{T.wf.noStageHistory}</EmptyState>
          ) : (
            <ol className="stack" style={{ listStyle: "none", padding: 0 }} aria-label={T.wf.stageHistory}>
              {data.history.map((h) => (
                <li key={h.id}>
                  <ItemHead
                    title={<strong>{serverLabel(h.label)}</strong>}
                    meta={
                      <span className="muted">
                        {[
                          serverLabel(h.response_mode_label) ?? labelFor(undefined, h.response_mode),
                          [h.set_by, h.office_code ? nameOf(h.office_code) : null].filter(Boolean).join(", "),
                          formatDateTime(h.set_at),
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    }
                  />
                  {h.note ? <div>{h.note}</div> : null}
                </li>
              ))}
            </ol>
          )}
        </>
      ) : null}
      {detail.workflow.set_stage ? (
        <div className="row">
          <Button variant="secondary" onClick={() => setOpen(true)}>
            {T.wf.setStage}
          </Button>
        </div>
      ) : null}
      {detail.workflow.set_stage ? (
        <StageDialog
          open={open}
          caseRef={caseRef}
          current={cur ? { stage: cur.stage, response_mode: cur.response_mode } : null}
          onClose={() => setOpen(false)}
          onDone={toast}
        />
      ) : null}
    </section>
  );
}

export function CustodyTab({ caseRef }: { caseRef: string }) {
  const query = useCase(caseRef);
  if (!query.data) return null;
  const detail = query.data;
  if (!detail.ownership.primary) return <EmptyState>{T.wf.noCustodyYet}</EmptyState>;
  return (
    <div className="stack">
      <Movement caseRef={caseRef} detail={detail} />
      <StageBlock caseRef={caseRef} detail={detail} />
    </div>
  );
}
