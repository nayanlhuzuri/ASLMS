"use client";

/**
 * One item of the next-date review list (design portal-next-dates, decision 4), as the columns of a `DataTable` row
 * (design portal-ui-polish, decision 15), used by the review
 * list and by the case page's "Waiting for you" panel: the case (left out on the case page), the order with "View
 * order" when stored and the login holds `documents.view`, the court's sentence clamped to two lines, why the order
 * asks for a date (design next-date-direct, decision 9: no clear date, no next date, a scanned copy, a date marked
 * wrong) with the date to answer by, the department when the login has more than one, and Enter Date. Never the alert
 * reference, the rule code or a score. Confirm and Not Correct are gone: a date the court gave is shown directly.
 *
 * Design portal-screen-fixes-work, decisions 11 and 18: the Next Date column has a fixed width of two lead columns, the
 * Actions column is left out when no row has an action, and a missed answer-by date reads "Answer was due …" in red.
 */
import { useState } from "react";

import { fileUrl } from "@/components/case/Orders";
import { Remark } from "@/components/files/Remark";
import { Button, CaseLink, type Column } from "@/components/ui";
import type { NextDateReviewItem } from "@/lib/api/types";
import { formatDate, istDay } from "@/lib/format";
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
/** The answer-by line: "Please answer by …", or "Answer was due …" in the danger text once the date has passed (IST). */
export function AnswerBy({ actBy }: { actBy: string | null | undefined }) {
  if (!actBy) return null;
  if (actBy < istDay()) return <span className={s.missed}>{T.nd.answerWasDue(formatDate(actBy))}</span>;
  return <span className={s.hint}>{T.nd.pleaseAnswerBy(formatDate(actBy))}</span>;
}

export function reviewColumns(
  { showCase, showDepartment, canViewOrder, onDone, onStale }: ReviewColumnsOptions,
  items: readonly NextDateReviewItem[] = [],
): Column<NextDateReviewItem>[] {
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
      // two lead columns (192 px), so the reason wraps between a few words, not one per line
      width: "calc(2 * var(--lead-w))",
      cell: (item) => (
        <div className={s.suggested} data-reason={item.reason ?? undefined}>
          <span>{reasonLabel(item)}</span>
          <AnswerBy actBy={item.act_by} />
        </div>
      ),
    },
  );
  if (showDepartment) {
    columns.push({ key: "department", header: T.nd.department, cell: (item) => item.departments.join(", ") || "—" });
  }
  // no row with an action (every item an old server's confirm item): no empty Actions column
  if (items.some((item) => item.kind === "enter")) {
    columns.push({
      key: "actions",
      header: T.nd.actions,
      // design control-spacing-sweep, decision 9 (item 12): on a card Enter Date takes the full width, with no label
      actions: true,
      cell: (item) => <ReviewActions item={item} onDone={onDone} onStale={onStale} />,
    });
  }
  return columns;
}
