/**
 * The modal's order rows with `INLINE_PDF` false (design portal-ui-redesign, decision 7; portal-cases-followups,
 * decision 10): the expanded row shows "Open in a new tab" and Download instead of the frame. The module value is
 * mocked for this file only.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Order } from "@/lib/api/types";
import { admin, REF } from "@/test/claimFixtures";
import { browserApi, renderWithClient } from "@/test/render";

import { OrderRow } from "./OrderRow";

vi.mock("@/lib/documents", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/documents")>();
  return { ...actual, INLINE_PDF: false };
});

const ORDER = {
  id: "o-1",
  order_no: "3",
  order_date: "2026-09-25",
  kind: "interim",
  order_details: "Issue notice",
  order_judge_name: null,
  download_status: "stored",
  document_id: "d-1",
  date_judgement_pronounced: null,
  date_judgement_reserved: null,
  is_reportable: null,
} as Order;

describe("INLINE_PDF false", () => {
  it("an expanded order offers Open in a new tab and Download, and mounts no frame", async () => {
    browserApi({ "GET /me": admin() });
    const { container } = renderWithClient(<OrderRow caseRef={REF} order={ORDER} />);
    await userEvent.click(await screen.findByRole("button", { name: /Issue notice/ }));
    expect(await screen.findByRole("link", { name: "Open in a new tab" })).toHaveAttribute(
      "href",
      `/api/backend/cases/${REF}/orders/o-1/file?disposition=inline`,
    );
    expect(screen.getByRole("link", { name: "Download PDF" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Print" })).toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
  });
});
