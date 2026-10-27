/**
 * The shared Claim dialog's Assign Now section (design claim-assign-wording, decision 2), as opened from search
 * results, the cause list and the court search: the heading, the explanation line, Responsible Unit and Dealing
 * Officer in one field row with Whole Department and No Dealing Officer Yet, no fieldset, and the claim body still
 * carrying `unit_code` / `officer_user_id`. The case page's Assign dialog is tested in `components/case/case.test.tsx`.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { admin, ADMIN_FNS, REF } from "@/test/claimFixtures";
import { browserApi, renderWithClient } from "@/test/render";

import { ClaimDialog } from "./dialogs";

const BASE = `/cases/${REF}`;

const PEOPLE = {
  departments: [],
  items: [
    { membership_id: "mm-1", user_id: "u-7", full_name: "Officer One", designation: "SO", office_code: "EDU", office_name: "Education", role_label: "Officer" },
  ],
  units: [{ code: "EDU-DSE", name: "Secondary Education" }],
  total: 1,
};

describe("inbox ClaimDialog: Assign Now section", () => {
  it("shows the heading, the line and the two fields in one row, and sends unit_code and officer_user_id", async () => {
    const api = browserApi({ "GET /me": admin(), "GET /custody/recipients": PEOPLE, [`POST ${BASE}/claim`]: {} });
    renderWithClient(<ClaimDialog open caseRef={REF} department="EDU" onClose={() => undefined} />);
    const dialog = await screen.findByRole("dialog", { name: "Claim This Case" });
    expect(await within(dialog).findByRole("heading", { name: "Assign Now (Optional)", level: 4 })).toBeInTheDocument();
    expect(within(dialog).getByText(/Choose who in the department handles this case\./)).toBeInTheDocument();
    expect(within(dialog).getByText(/use Send Case on the case page/)).toBeInTheDocument();
    const unit = within(dialog).getByLabelText("Responsible Unit");
    const officer = within(dialog).getByLabelText("Dealing Officer");
    expect(within(unit).getByRole("option", { name: "Whole Department" })).toHaveValue("");
    expect(within(officer).getByRole("option", { name: "No Dealing Officer Yet" })).toHaveValue("");
    expect(
      within(dialog).getByText("An office under the department that is responsible for the case. It will see the case."),
    ).toBeInTheDocument();
    expect(dialog.querySelector("fieldset, legend")).toBeNull();
    expect(unit.closest(".row")).not.toBeNull();
    expect(unit.closest(".row")).toBe(officer.closest(".row"));
    await waitFor(() => expect(within(officer).getByRole("option", { name: /Officer One/ })).toBeInTheDocument());
    await userEvent.selectOptions(unit, "EDU-DSE");
    await userEvent.selectOptions(officer, "u-7");
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    await waitFor(() =>
      expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ office_code: "EDU", unit_code: "EDU-DSE", officer_user_id: "u-7" }),
    );
  });

  it("left empty, nothing is assigned; without cases.allot the section does not show", async () => {
    const api = browserApi({ "GET /me": admin(), "GET /custody/recipients": PEOPLE, [`POST ${BASE}/claim`]: {} });
    const { unmount } = renderWithClient(<ClaimDialog open caseRef={REF} department="EDU" onClose={() => undefined} />);
    const dialog = await screen.findByRole("dialog", { name: "Claim This Case" });
    await within(dialog).findByLabelText("Dealing Officer");
    await userEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ office_code: "EDU" }));
    unmount();

    browserApi({ "GET /me": admin(ADMIN_FNS.filter((f) => f !== "cases.allot")), "GET /custody/recipients": PEOPLE });
    renderWithClient(<ClaimDialog open caseRef={REF} department="EDU" onClose={() => undefined} />);
    const again = await screen.findByRole("dialog", { name: "Claim This Case" });
    await within(again).findByLabelText("Note (Optional)");
    expect(within(again).queryByRole("heading", { name: "Assign Now (Optional)" })).toBeNull();
    expect(within(again).queryByLabelText("Dealing Officer")).toBeNull();
  });
});
