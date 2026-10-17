"use client";

/**
 * One item of the next-date review list (design portal-next-dates, decision 4), as a table row, used by the review
 * list and by the case page's "Waiting for you" panel: the case (left out on the case page), the order with "View
 * order" when stored and the login holds `documents.view`, the court's sentence clamped to two lines, what is asked
 * (a suggested date to confirm, or a date to enter, with the scanned-copy wording) with the date to answer by, the
 * department when the login has more than one, and the buttons. Never the alert reference, the rule code or a score.
 */
import { useState } from "react";

import { fileUrl } from "@/components/case/Orders";
import { Remark } from "@/components/files/Remark";
import { Button, CaseLink } from "@/components/ui";
import type { NextDateReviewItem } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { isScannedItem, ruleHint } from "@/lib/nextDates";

import { caseName } from "./common";
import { ConfirmNextDate, EnterNextDate, RejectNextDate, type DialogOutcome } from "./Dialogs";
import s from "./nextdates.module.css";

export interface ReviewItemProps extends DialogOutcome {
  item: NextDateReviewItem;
  /** The case column (the review list); the case page leaves it out. */
  showCase: boolean;
  /** The department column: only for a login with more than one department membership. */
  showDepartment: boolean;
  /** The login holds `documents.view`. */
  canViewOrder: boolean;
}

export function ReviewItem({ item, showCase, showDepartment, canViewOrder, onDone, onStale }: ReviewItemProps) {
  const [open, setOpen] = useState<"confirm" | "reject" | "enter" | null>(null);
  const name = caseName(item.case);
  const hint = item.kind === "confirm" ? ruleHint(item.rule) : null;
  const close = () => setOpen(null);
  const outcome = { onDone, onStale };
  return (
    <tr>
      {showCase ? (
        <td>
          <CaseLink value={item.case} />
          {item.case.cnr && item.case.case_no_text ? <div className="mono muted">{item.case.cnr}</div> : null}
        </td>
      ) : null}
      <td>
        {item.order ? (
          <>
            <div>{T.nd.orderOf(formatDate(item.order.order_date))}</div>
            <div className="muted">{T.nd.orderNo(item.order.order_no)}</div>
            {item.order.document_id && canViewOrder ? (
              <a href={fileUrl(item.case.ref_no, item.order.id, "inline")} target="_blank" rel="noopener noreferrer">
                {T.nd.viewOrder}
              </a>
            ) : null}
          </>
        ) : (
          "—"
        )}
      </td>
      <td>{item.phrase ? <Remark text={T.nd.quoted(item.phrase)} /> : <span className="muted">—</span>}</td>
      <td>
        <div className={s.suggested}>
          {item.kind === "confirm" ? (
            <>
              <span>{T.nd.suggested}</span>
              <span className={s.date}>{formatDate(item.next_date)}</span>
              {hint ? <span className={s.hint}>{hint}</span> : null}
            </>
          ) : (
            <span>{isScannedItem(item) ? T.nd.enterScanned : T.nd.enterNeeded}</span>
          )}
          <span className={s.hint}>{T.nd.pleaseAnswerBy(formatDate(item.act_by))}</span>
        </div>
      </td>
      {showDepartment ? <td>{item.departments.join(", ") || "—"}</td> : null}
      <td>
        <div className={s.actions}>
          {item.kind === "confirm" ? (
            <>
              <Button onClick={() => setOpen("confirm")} aria-label={T.nd.confirmFor(name)}>
                {T.nd.confirm}
              </Button>
              <Button variant="secondary" onClick={() => setOpen("reject")} aria-label={T.nd.notCorrectFor(name)}>
                {T.nd.notCorrect}
              </Button>
            </>
          ) : (
            <Button onClick={() => setOpen("enter")} aria-label={T.nd.enterFor(name)}>
              {T.nd.enterDate}
            </Button>
          )}
        </div>
        {item.kind === "confirm" ? (
          <>
            <ConfirmNextDate item={item} open={open === "confirm"} onClose={close} {...outcome} />
            <RejectNextDate item={item} open={open === "reject"} onClose={close} {...outcome} />
          </>
        ) : (
          <EnterNextDate
            caseRef={item.case.ref_no}
            name={name}
            orderId={item.id}
            phrase={item.phrase}
            open={open === "enter"}
            onClose={close}
            {...outcome}
          />
        )}
      </td>
    </tr>
  );
}
