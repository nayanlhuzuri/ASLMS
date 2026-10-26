import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Permission } from "@/lib/api/types";
import { caseDetail } from "@/test/caseDetail";
import { nav, resetNav } from "@/test/nav";
import { browserApi, makeMe, renderWithClient } from "@/test/render";

import { CaseFrame } from "./CaseFrame";

// design case-ref-court-prefix, decision 20: this alias test keeps an old GOA case number on purpose. The API resolves
// the old number and answers with the current `ref_no`; the portal then replaces the address.
const OLD = "ASLMS-GOA-CASE-2026-000001";
const NEW = "ASLMS-GHC-CASE-2026-000001";
const CNR = "ASHC010012342026";
const READ: Permission[] = ["cases.view_scope", "documents.view", "documents.download"];

function me() {
  return makeMe(READ, "dept_admin", {
    memberships: [
      {
        id: "m-1",
        office: { code: "EDU", name: "Education", kind: "department" },
        department_code: "EDU",
        designation: null,
        role: "dept_admin",
        is_primary: true,
        is_active: true,
        functions: READ,
      },
    ],
  });
}

describe("an old case number in the address", () => {
  beforeEach(() => resetNav());

  it("is replaced by the current number, keeping the tab and the query", async () => {
    resetNav(`/cases/${OLD}/orders`, "page=2");
    browserApi({ "GET /me": me(), [`GET /cases/${OLD}`]: caseDetail() });
    renderWithClient(<CaseFrame caseRef={OLD}>body</CaseFrame>);
    expect(await screen.findByText("body")).toBeInTheDocument();
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`/cases/${NEW}/orders?page=2`));
    expect(nav.replace).toHaveBeenCalledTimes(1);
  });

  it("the current number, a CNR or an id is left alone", async () => {
    for (const ref of [NEW, CNR, "c-1"]) {
      resetNav(`/cases/${ref}/orders`);
      browserApi({ "GET /me": me(), [`GET /cases/${ref}`]: caseDetail() });
      const view = renderWithClient(<CaseFrame caseRef={ref}>body</CaseFrame>);
      expect(await screen.findByText("body")).toBeInTheDocument();
      expect(nav.replace).not.toHaveBeenCalled();
      view.unmount();
    }
  });
});
