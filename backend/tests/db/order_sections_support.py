"""Shared helpers for the order-sections tests (design `order-sections`): an order's text on the court's template
with chosen printed values, an order sharing another order's PDF, and readers of the readings."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from aslms.domain.cases import Case
from aslms.domain.documents import Document, DownloadStatus, Order, OrderKind, OrderSection
from aslms.services import order_sections as svc

BODY = (
    "Heard Mr. Advocate A, learned counsel for the petitioner. Also heard Ms. Advocate C, learned Standing\n"
    "Counsel, Education Department.\n"
    "Issue notice to the respondents. List this matter on 04.03.2026.\n"
)
JUDGMENT_BODY = (
    "1.      Heard Mr. Advocate K, learned Standing Counsel for the appellants.\n"
    "2.      The facts of the case, in brief, are that the respondent was appointed in 2009 and was denied the\n"
    "benefit under Section 3 of the Assam Services (Pay) Act, 2017.\n"
    "3.      Learned counsel for the appellants submits that the claim is barred, relying on (2015) 4 SCC 123.\n"
    "4.      In view of the above, the writ petition is allowed. The respondent authorities are directed to\n"
    "release the arrears within 30 (thirty) days from the date of this order.\n"
)


def order_text(
    *,
    cnr: str | None,
    case_no: str | None,
    day: str = "28.01.2026",
    heading: str = "ORDER",
    body: str = BODY,
    linked: list[str] | None = None,
    coram: str = "HONOURABLE MR. JUSTICE JUDGE A",
) -> str:
    """A two-page order on the court's template; the cause title and advocates are masked placeholders."""
    lines = ["Page No.# 1/2"]
    if cnr:
        lines.append(cnr)
    lines += ["       ", "undefined", "                THE GAUHATI HIGH COURT "]
    lines.append("(HIGH COURT OF ASSAM, NAGALAND, MIZORAM AND ARUNACHAL PRADESH) ")
    if case_no:
        lines.append(f"Case No. : {case_no} ")
    lines += ["PETITIONER A ", "S/O PARENT A, R/O MASKED", "VERSUS ", "THE STATE OF ASSAM AND 3 ORS "]
    lines.append("Advocate for the Petitioner     : MR. ADVOCATE A ")
    lines.append("Advocate for the Respondent : SC, SEC. EDU.  ")
    for lc in linked or []:
        lines += [f" Linked Case : {lc}", "PETITIONER Z", " VERSUS", "THE STATE OF ASSAM", " ------------"]
    lines += ["", "\fPage No.# 2/2", "BEFORE", coram, f"{heading} ", f"Date :  {day}", body.rstrip("\n")]
    lines += ["JUDGE", "Comparing Assistant"]
    return "\n".join(lines).strip()


def share_pdf(
    s: Session, case: Case, other: Order, *, order_no: str = "9", order_date: date | None = None
) -> Order:
    """An order of `case` whose PDF is `other`'s (a common order: one PDF, several cases)."""
    order = Order(
        case_id=case.id,
        order_no=order_no,
        order_date=order_date or other.order_date,
        kind=other.kind,
        order_details="ORDER",
        document_id=other.document_id,
        download_status=DownloadStatus.STORED,
    )
    s.add(order)
    s.flush()
    return order


def readings(s: Session, order: Order) -> list[OrderSection]:
    return list(
        s.scalars(
            sa.select(OrderSection)
            .where(OrderSection.order_id == order.id)
            .order_by(OrderSection.created_at, OrderSection.id)
            .execution_options(populate_existing=True)
        ).all()
    )


def current(s: Session, order: Order) -> OrderSection | None:
    return svc.current_for(s, order.id)


def doc_of(s: Session, order: Order) -> Document:
    return s.get(Document, order.document_id)


def set_kind(s: Session, order: Order, kind: OrderKind) -> Order:
    order.kind = kind
    s.flush()
    return order
