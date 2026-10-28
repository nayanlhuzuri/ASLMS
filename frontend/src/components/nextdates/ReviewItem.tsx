"use client";

/**
 * One item of the next-date review list (design portal-next-dates, decision 4), as the columns of a `DataTable` row
 * (design portal-ui-polish, decision 15), used by the review
 * list and by the case page's "Waiting for you" panel: the case (left out on the case page), the order with "View
 * order" when stored and the login holds `documents.view`, the court's sentence clamped to two lines, why the order
 * asks for a date (design next-date-direct, decision 9: no clear date, no next date, a scanned copy, a date marked
 * wrong) with the date to answer by, the department when the login has more than one, and Enter Date. Never the alert
 * reference, the rule code or a score. Confirm and Not Correct are gone: a date the court gave is shown directly.
 */
import { useState } from "react";

import { fileUrl } from "@/components/case/Orders";
import { Remark } from "@/components/files/Remark";
import { Button, CaseLink, type Column } from "@/components/ui";
import type { NextDateReviewItem } from "@/lib/api/types";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";
import { reasonLabel } from "@/lib/nextDates";

import { caseName } from "./common";
import { EnterNextDate, type DialogOutcome } from "./Dialogs";
import s from "./nextdates.module.css";

export interface ReviewColumnsOptions extends DialogOutcome {
  /** The case column (the review list); the case page leaves it out. */
  showCase: boolean;
  /** The department column: only for a login with more than one department membership. */
  showDepartment: boolean;
  /** The login holds `documents.view`. */
  canViewOrder: boolean;
}

/**
 * The buttons of one item with their dialogs (the row's only state). All secondary: a list's rows never hold the page's
 * one primary (decision 16; design portal-ui-polish, decision 21).
 */
function ReviewActions({ item, onDone, onStale }: { item: NextDateReviewItem } & DialogOutcome) {
  const [open, setOpen] = useState(false);
  const name = caseName(item.case);
  if (item.kind !== "enter") return null; // an old server's confirm item: nothing a person may do any more
  return (
    <>
      <div className={s.actions}>
        <Button variant="secondary" onClick={() => setOpen(true)} aria-label={T.nd.enterFor(name)}>
          {T.nd.enterDate}
        </Button>
      </div>
      <EnterNextDate
        caseRef={item.case.ref_no}
        name={name}
        orderId={item.id}
        phrase={item.phrase}
        open={open}
        onClose={() => setOpen(false)}
        onDone={onDone}
        onStale={onStale}
      />
    </>
  );
}

/** The columns of the review table (design portal-ui-polish, decision 15: one `DataTable`, cards on phones). */
export function reviewColumns({ showCase, showDepartment, canViewOrder, onDone, onStale }: ReviewColumnsOptions): Column<NextDateReviewItem>[] {
  const columns: Column<NextDateReviewItem>[] = [];
  if (showCase) {
    columns.push({
      key: "case",
      header: T.nd.case,
      primary: true,
      cell: (item) => (
        <>
          <CaseLink value={item.case} />
          {item.case.cnr && item.case.case_no_text ? <div className="mono muted">{item.case.cnr}</div> : null}
        </>
      ),
    });
  }
  columns.push(
    {
      key: "order",
      header: T.nd.order,
      primary: !showCase,
      cell: (item) =>
        item.order ? (
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
        ),
    },
    {
      key: "says",
      header: T.nd.says,
      cell: (item) => (item.phrase ? <Remark text={T.nd.quoted(item.phrase)} /> : <span className="muted">—</span>),
    },
    {
      key: "next",
      header: T.nd.nextDate,
      cell: (item) => (
        <div className={s.suggested} data-reason={item.reason ?? undefined}>
          <span>{reasonLabel(item)}</span>
          <span className={s.hint}>{T.nd.pleaseAnswerBy(formatDate(item.act_by))}</span>
        </div>
      ),
    },
  );
  if (showDepartment) {
    columns.push({ key: "department", header: T.nd.department, cell: (item) => item.departments.join(", ") || "—" });
  }
  columns.push({
    key: "actions",
    header: T.nd.actions,
    cell: (item) => <ReviewActions item={item} onDone={onDone} onStale={onStale} />,
  });
  return columns;
}
