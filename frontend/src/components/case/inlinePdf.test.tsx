/**
 * The tabs with `INLINE_PDF` false (design portal-cases-followups, decision 10): PDFs offer Download only with the
 * hint "Opens as a download"; images keep View. The module value is mocked for this file only.
 */
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "@/lib/api/types";
import { resetNav } from "@/test/nav";
import { browserApi, makeMe, renderWithClient } from "@/test/render";

import { Documents } from "./Documents";
import { Notes } from "./Notes";
import { Orders } from "./Orders";

vi.mock("@/lib/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/documents")>();
  return {
    ...actual,
    INLINE_PDF: false,
    canViewInline: (mime: string | null | undefined) => actual.canViewInline(mime, false),
    pdfDownloadOnly: (mime: string | null | undefined) => actual.pdfDownloadOnly(mime, false),
  };
});

const REF = "ASLMS-GOA-CASE-2026-000001";
const BASE = `/cases/${REF}`;
const READ: Permission[] = ["cases.view_scope", "documents.view", "documents.download"];

beforeEach(() => resetNav(BASE));

describe("INLINE_PDF false", () => {
  it("orders: the expanded row offers Open in a new tab and Download PDF, no inline frame (portal-ui-redesign, decision 7)", async () => {
    browserApi({
      "GET /me": makeMe(READ),
      [`GET ${BASE}/orders`]: {
        items: [
          { id: "o-1", order_no: "3", order_date: "2026-09-25", kind: "interim", order_judge_name: "X", download_status: "stored", document_id: "d-1", order_details: null, is_reportable: null, date_judgement_pronounced: null, date_judgement_reserved: null },
        ],
        total: 1,
      },
    });
    renderWithClient(<Orders caseRef={REF} />);
    await userEvent.click(await screen.findByRole("button", { name: /interim/ }));
    expect(screen.getByRole("link", { name: "Open in a New Tab" })).toHaveAttribute("href", `/api/backend${BASE}/orders/o-1/file?disposition=inline`);
    expect(screen.getByRole("link", { name: "Download PDF" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Print" })).toBeNull();
    expect(document.querySelector("iframe")).toBeNull();
  });

  it("documents: a PDF downloads with the hint, an image keeps View", async () => {
    const doc = (id: string, mime: string) => ({
      id,
      doc_group: "court_filing",
      doc_type: "affidavit",
      doc_type_label: "Affidavit",
      doc_date: "2026-09-01",
      description: `${id} description`,
      original_filename: id,
      mime,
      size_bytes: 10,
      page_count: null,
      uploaded_by: null,
      office: null,
      visibility: "case_scope",
      assistant_available: false,
      sourcetrace_status: "not_applicable",
      text_status: "extracted",
      archived_at: null,
    });
    browserApi({
      "GET /me": makeMe(READ),
      [`GET ${BASE}/documents`]: (call: { url: string }) =>
        call.url.includes("group=court_filing")
          ? { items: [doc("d-pdf", "application/pdf"), doc("d-img", "image/jpeg")], total: 2 }
          : { items: [], total: 0 },
    });
    renderWithClient(<Documents caseRef={REF} />);
    const pdfRow = (await screen.findByText("d-pdf description")).closest("tr")!;
    expect(within(pdfRow).queryByRole("link", { name: "View" })).toBeNull();
    expect(within(pdfRow).getByText("Opens As a Download")).toBeInTheDocument();
    const imgRow = screen.getByText("d-img description").closest("tr")!;
    expect(within(imgRow).getByRole("link", { name: "View" })).toBeInTheDocument();
    expect(within(imgRow).queryByText("Opens As a Download")).toBeNull();
  });

  it("note attachments: a PDF downloads with the hint", async () => {
    browserApi({
      "GET /me": makeMe(READ),
      [`GET ${BASE}/notes`]: {
        items: [
          {
            id: "n-1",
            ref_no: "ASLMS/EDU/NOTE/2026/000001",
            seq_no: 1,
            kind: "remark",
            kind_label: "Remark",
            body: "with a pdf",
            author: { name: "Edu Admin", designation: null, office_code: "EDU", role: "dept_admin" },
            created_at: "2026-10-01T10:00:00Z",
            visibility: "case_scope",
            attachments: [{ id: "a-pdf", ref_no: null, doc_type: "other", original_filename: "a.pdf", mime: "application/pdf", size_bytes: 10 }],
            supersedes: null,
            superseded_by: null,
            custody_leg_seq_no: null,
            drafted_at: null,
          },
        ],
        total: 1,
      },
    });
    renderWithClient(<Notes caseRef={REF} />);
    await screen.findByText("with a pdf");
    expect(screen.queryByRole("link", { name: "View" })).toBeNull();
    expect(screen.getByRole("link", { name: "Download" })).toBeInTheDocument();
    expect(screen.getByText("Opens As a Download")).toBeInTheDocument();
  });
});
