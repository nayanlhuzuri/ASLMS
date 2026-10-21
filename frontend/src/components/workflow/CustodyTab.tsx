"use client";

/**
 * The custody card's facts (shared with the Overview) and the "Custody and stage" tab (design portal-workflow,
 * decisions 8, 9; plan §5.7): the card with Send and Recall; the movement record, oldest first and paged by 50, with
 * the remark only when the API returns it; the stage block with the current stage, the history newest first, the
 * gaps ("Not recorded", guided, not enforced) and Set stage. An unclaimed case has no custody and no actions.
 */
import { useState } from "react";

import { Badge, Button, EmptyState, ErrorBanner, Loading, Notice, Pagination, DataTable } from "@/components/ui";
import { useCase, useCustodyHistory, useStages, useWorkflowCodes } from "@/lib/api/hooks";
import type { CaseDetail, CustodyCard } from "@/lib/api/types";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { PAGE } from "@/lib/params";

import { CustodyActions } from "./CustodyDialogs";
import { StageDialog } from "./StageDialog";
import cs from "@/components/case/case.module.css";

export function CustodyFacts({ card }: { card: CustodyCard }) {
  return (
    <dl className={cs.facts}>
      <div>
        <dt>{T.case.holder}</dt>
        <dd>
          {card.holder_office ? `${card.holder_office.code} — ${card.holder_office.name}` : "—"}
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
        <dd>{card.pending_action_label}</dd>
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
          <dd>{[card.sent_by.name, card.sent_by.designation, card.sent_by.office_code].filter(Boolean).join(", ")}</dd>
        </div>
      ) : null}
      {card.remark ? (
        <div>
          <dt>{T.case.remark}</dt>
          <dd>{card.remark}</dd>
        </div>
      ) : null}
    </dl>
  );
}

function Movement({ caseRef, detail }: { caseRef: string; detail: CaseDetail }) {
  const [offset, setOffset] = useState(0);
  const history = useCustodyHistory(caseRef, offset, PAGE);
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
          <EmptyState>{T.wf.noLegs}</EmptyState>
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
                      <span className="mono">{leg.holder_office.code}</span> {leg.holder_office.name}
                      {leg.holder_user ? (
                        <div>
                          {leg.holder_user.full_name}
                          {leg.holder_designation ? `, ${leg.holder_designation}` : ""}
                        </div>
                      ) : null}
                    </>
                  ),
                },
                { key: "reason", header: T.wf.reason, cell: (leg) => leg.reason_label },
                { key: "action", header: T.case.pendingAction, cell: (leg) => leg.pending_action_label },
                { key: "due", header: T.case.due, cell: (leg) => formatDate(leg.due_date) },
                { key: "started", header: T.wf.started, cell: (leg) => formatDateTime(leg.started_at) },
                {
                  key: "by",
                  header: T.wf.sentByCol,
                  cell: (leg) => [leg.actor_name, leg.actor_designation, leg.actor_office_code].filter(Boolean).join(", ") || "—",
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
  const [notice, setNotice] = useState<string | null>(null);
  const labelOf = (code: string) => codes.data?.stages.find((s) => s.code === code)?.label ?? code.replace(/_/g, " ");
  const data = stages.data;
  const cur = data?.current ?? null;
  return (
    <section className="card stack" aria-label={T.wf.stageBlock}>
      <h2>{T.wf.stageBlock}</h2>
      {notice ? <Notice>{notice}</Notice> : null}
      {stages.isPending ? <Loading /> : null}
      <ErrorBanner error={stages.error} onRetry={() => stages.refetch()} />
      {data ? (
        <>
          {cur ? (
            <dl className={cs.facts}>
              <div>
                <dt>{T.wf.currentStage}</dt>
                <dd>
                  <strong>{cur.label}</strong>
                  {cur.phase ? <span className="muted"> · {cur.phase}</span> : null}
                </dd>
              </div>
              <div>
                <dt>{T.wf.responseMode}</dt>
                <dd>{cur.response_mode_label ?? cur.response_mode}</dd>
              </div>
              <div>
                <dt>{T.wf.setBy}</dt>
                <dd>
                  {[cur.set_by, cur.office_code].filter(Boolean).join(", ") || "—"} · {formatDateTime(cur.set_at)}
                </dd>
              </div>
              {cur.note ? (
                <div>
                  <dt>{T.wf.stageNote}</dt>
                  <dd>{cur.note}</dd>
                </div>
              ) : null}
            </dl>
          ) : (
            <p className="muted">{T.case.noStage}</p>
          )}
          {data.gaps.length > 0 ? <p className="muted">{T.wf.notRecorded(data.gaps.map(labelOf).join(", "))}</p> : null}
          <h3>{T.wf.stageHistory}</h3>
          {data.history.length === 0 ? (
            <p className="muted">{T.wf.noStageHistory}</p>
          ) : (
            <ol className="stack" style={{ listStyle: "none", padding: 0 }} aria-label={T.wf.stageHistory}>
              {data.history.map((h) => (
                <li key={h.id}>
                  <strong>{h.label}</strong> <span className="muted">· {h.response_mode_label ?? h.response_mode}</span>{" "}
                  <span className="muted">
                    · {[h.set_by, h.office_code].filter(Boolean).join(", ")} · {formatDateTime(h.set_at)}
                  </span>
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
          onDone={setNotice}
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
