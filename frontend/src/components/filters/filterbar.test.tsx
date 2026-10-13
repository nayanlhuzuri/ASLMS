import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { nav, resetNav } from "@/test/nav";
import { browserApi, renderWithClient } from "@/test/render";

import { FilterBar } from "./FilterBar";

const ROUTES = {
  "GET /custody/recipients": {
    departments: [
      { code: "EDU", name: "Education" },
      { code: "FIN", name: "Finance" },
    ],
    items: [],
    units: [],
    total: 2,
  },
  "GET /reference/case-types": [
    { case_type_code: 1, short_name: "WP(C)", full_name: "Writ Petition (Civil)", type_name: "WP(C)" },
  ],
  "GET /reference/benches": {
    from: "2026-07-16",
    to: "2026-10-13",
    court_numbers: [
      { court_no: "3", last_listed: "2026-10-13", entries: 40 },
      { court_no: "10", last_listed: "2026-10-12", entries: 12 },
    ],
    benches: [
      { text: "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA", last_listed: "2026-10-13", entries: 30 },
      { text: "HONOURABLE THE CHIEF JUSTICE, HONOURABLE MR. JUSTICE SOUMITRA SAIKIA", last_listed: "2026-10-10", entries: 9 },
    ],
  },
};

beforeEach(() => {
  resetNav("/inbox/recommended");
});

describe("FilterBar (portal-filters, decision 9)", () => {
  it("requests nothing until Apply, then writes every field at once", async () => {
    browserApi(ROUTES);
    renderWithClient(<FilterBar list="recommended" params={{ department: "EDU" }} total={12} />);
    expect(screen.getByText("12 cases match")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Words/), "ram kumar");
    await userEvent.selectOptions(screen.getByLabelText("Cause-list date"), "range");
    await userEvent.type(screen.getByLabelText("Cause-list date: from"), "2026-10-01");
    await userEvent.type(screen.getByLabelText("Cause-list date: to"), "2026-10-07");
    await userEvent.selectOptions(screen.getByLabelText("Next hearing"), "n7");
    expect(nav.replace).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledTimes(1);
    expect(nav.replace).toHaveBeenCalledWith(
      "/inbox/recommended?department=EDU&q=ram+kumar&listed_from=2026-10-01&listed_to=2026-10-07&next=n7",
    );
  });

  it("Enter in a field submits", async () => {
    browserApi(ROUTES);
    renderWithClient(<FilterBar list="recommended" params={{}} />);
    await userEvent.type(screen.getByLabelText(/^Words/), "kathar{Enter}");
    expect(nav.replace).toHaveBeenCalledWith("/inbox/recommended?q=kathar");
  });

  it("A date writes both ends the same", async () => {
    browserApi(ROUTES);
    renderWithClient(<FilterBar list="recommended" params={{}} />);
    await userEvent.selectOptions(screen.getByLabelText("Cause-list date"), "date");
    await userEvent.type(screen.getByLabelText("Cause-list date: date"), "2026-09-25");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/recommended?listed_from=2026-09-25&listed_to=2026-09-25");
  });

  it("More filters opens by itself when one of its fields is in the URL", async () => {
    browserApi(ROUTES);
    const { unmount } = renderWithClient(<FilterBar list="recommended" params={{}} />);
    const more = screen.getByRole("button", { name: "More filters" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Year")).toBeNull();
    await userEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Year")).toBeInTheDocument();
    unmount();
    renderWithClient(<FilterBar list="recommended" params={{ year: "2025" }} />);
    expect(screen.getByRole("button", { name: "More filters" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Year")).toHaveValue("2025");
  });

  it("a chip's remove button drops that filter and resets the offset", async () => {
    browserApi(ROUTES);
    renderWithClient(
      <FilterBar list="recommended" params={{ department: "EDU", bench: "SAIKIA", year: "2025", offset: "50" }} />,
    );
    const chips = screen.getByRole("list", { name: "Applied filters" });
    expect(within(chips).getByText("Year: 2025")).toBeInTheDocument();
    await userEvent.click(within(chips).getByRole("button", { name: "Remove filter Bench: SAIKIA" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/recommended?department=EDU&year=2025");
  });

  it("Clear all keeps only the tab's own fixed keys", async () => {
    resetNav("/inbox/transfers");
    browserApi(ROUTES);
    renderWithClient(
      <FilterBar
        list="transfers"
        params={{ department: "EDU", direction: "out", year: "2025", status: "requested", other_office: "FIN", offset: "50" }}
        own={[{ key: "status", kind: "select", label: "Transfer status", options: [{ value: "requested", label: "Requested" }] }]}
      />,
    );
    expect(screen.getByText("Transfer status: Requested")).toBeInTheDocument();
    expect(screen.getByText("Other department: FIN")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear all" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/transfers?department=EDU&direction=out");
  });

  it("validation errors are linked to their fields and block the request", async () => {
    browserApi(ROUTES);
    renderWithClient(<FilterBar list="recommended" params={{}} />);
    await userEvent.type(screen.getByLabelText(/^Words/), "ab");
    await userEvent.selectOptions(screen.getByLabelText("Next hearing"), "range");
    await userEvent.type(screen.getByLabelText("Next hearing: from"), "2026-11-02");
    await userEvent.type(screen.getByLabelText("Next hearing: to"), "2026-11-01");
    await userEvent.click(screen.getByRole("button", { name: "More filters" }));
    await userEvent.type(screen.getByLabelText("Year"), "202");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(nav.replace).not.toHaveBeenCalled();
    for (const [label, message] of [
      ["Year", "Year is four digits, 1900 to 2100."],
      ["Next hearing: to", "The start date is after the end date."],
    ] as const) {
      const input = screen.getByLabelText(label);
      expect(input).toHaveAttribute("aria-invalid", "true");
      const described = input.getAttribute("aria-describedby")!;
      expect(document.getElementById(described)).toHaveTextContent(message);
    }
    expect(screen.getByLabelText(/^Words/)).toHaveAttribute("aria-invalid", "true");
  });

  it("the bench field offers the suggestions of /reference/benches; Court lists its court numbers", async () => {
    browserApi(ROUTES);
    renderWithClient(<FilterBar list="recommended" params={{ bench: "SAIKIA" }} />);
    const bench = screen.getByLabelText("Bench (judge names)");
    const listId = bench.getAttribute("list")!;
    await waitFor(() => expect(document.getElementById(listId)!.querySelectorAll("option")).toHaveLength(2));
    expect(document.getElementById(listId)!.querySelector("option")!.getAttribute("value")).toBe(
      "HONOURABLE MR. JUSTICE SOUMITRA SAIKIA",
    );
    const court = screen.getByLabelText("Court");
    await waitFor(() => expect(within(court).getAllByRole("option").map((o) => o.textContent)).toEqual(["Any court", "Court 3", "Court 10"]));
  });

  it("the department field shows where the list declares it, with the given choices", async () => {
    browserApi(ROUTES);
    const { unmount } = renderWithClient(<FilterBar list="recommended" params={{ year: "2025" }} />);
    expect(screen.queryByLabelText("Department")).toBeNull();
    unmount();
    renderWithClient(
      <FilterBar list="held_owned" params={{ owner: "EDU" }} ownerOptions={[{ value: "EDU", label: "EDU" }]} />,
    );
    const owner = screen.getByLabelText("Department");
    expect(within(owner).getAllByRole("option").map((o) => o.textContent)).toEqual(["Any department", "EDU"]);
  });
});
