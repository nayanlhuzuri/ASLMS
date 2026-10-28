/** The kit's sort (design list-search, decisions 5, 27-29, 33 and 35). */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearAllUpdates } from "@/components/filters/NoCaseMatches";
import type { Params } from "@/lib/params";
import type { SortState } from "@/lib/sort";
import { useListState } from "@/lib/useListState";
import { nav, resetNav } from "@/test/nav";

import { DataTable, sortByColumn, sortOptionsOf, SortHeader, type Column } from "./data";
import { ListSort, ListToolbar, OrderLine } from "./listSearch";

interface Row {
  id: string;
  name: string;
  next: string | null;
  score: number;
}

const ROWS: Row[] = [
  { id: "a", name: "Bora", next: "2026-11-05", score: 0.5 },
  { id: "b", name: "Ahmed", next: null, score: 0.9 },
  { id: "c", name: "Das", next: "2026-10-20", score: 0.7 },
];

const COLUMNS: Column<Row>[] = [
  { key: "name", header: "Name", primary: true, sort: { type: "text", value: (r) => r.name }, cell: (r) => r.name },
  { key: "next", header: "Next Hearing", sort: { type: "date", firstDir: "asc", value: (r) => r.next }, cell: (r) => r.next ?? "—" },
  { key: "score", header: "Score", sort: { type: "number", value: (r) => r.score }, cell: (r) => String(r.score) },
  { key: "note", header: "Note", cell: () => "x" },
];

function Table({ initial = null }: { initial?: SortState | null }) {
  const [sort, setSort] = useState<SortState | null>(initial);
  const [stacked, setStacked] = useState(false);
  const options = sortOptionsOf(COLUMNS);
  return (
    <>
      <ListToolbar
        sort={stacked ? <ListSort options={options} sort={sort} onSort={setSort} defaultLabel="Name, A to Z" /> : null}
        order={<OrderLine options={options} sort={sort} defaultLabel="Name, A to Z" onReset={() => setSort(null)} />}
      />
      <DataTable
        caption="People"
        rows={sortByColumn(ROWS, COLUMNS, sort)}
        rowKey={(r) => r.id}
        columns={COLUMNS}
        sort={sort}
        onSort={setSort}
        defaultSort={{ key: "name", dir: "asc" }}
        onStackedChange={setStacked}
      />
    </>
  );
}

const names = () => screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0]!.textContent);
const header = (name: string) => screen.getByRole("columnheader", { name: new RegExp(name) });

function phone(on: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: on && query.includes("max-width: 819px"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

beforeEach(() => {
  resetNav("/inbox/department");
  phone(false);
});

describe("the header sort (decision 27)", () => {
  it("draws a sortable header as a button inside the th with its Title Case text; others stay plain", () => {
    render(<Table />);
    const th = header("Next Hearing");
    expect(within(th).getByRole("button", { name: "Next Hearing" })).toBeInTheDocument();
    expect(within(header("Note")).queryByRole("button")).toBeNull();
  });

  it("Enter and Space press the header", async () => {
    render(<Table />);
    within(header("Score")).getByRole("button").focus();
    await userEvent.keyboard("{Enter}");
    expect(names()).toEqual(["Ahmed", "Das", "Bora"]);
    await userEvent.keyboard(" ");
    expect(names()).toEqual(["Bora", "Das", "Ahmed"]);
  });

  it("cycles the first direction by type, the other direction, then the default", async () => {
    render(<Table />);
    const next = within(header("Next Hearing")).getByRole("button");
    await userEvent.click(next); // a date ahead starts with the earliest; blanks last
    expect(names()).toEqual(["Das", "Bora", "Ahmed"]);
    await userEvent.click(next);
    expect(names()).toEqual(["Bora", "Das", "Ahmed"]);
    await userEvent.click(next);
    expect(names()).toEqual(["Bora", "Ahmed", "Das"]); // the API's order again
    const score = within(header("Score")).getByRole("button");
    await userEvent.click(score); // a number starts with the highest
    expect(names()).toEqual(["Ahmed", "Das", "Bora"]);
    const name = within(header("Name")).getByRole("button");
    await userEvent.click(name); // text starts A to Z
    expect(names()).toEqual(["Ahmed", "Bora", "Das"]);
  });

  it("sets aria-sort on the sorted th only, and on the default column when no sort is set", async () => {
    render(<Table />);
    expect(header("Name")).toHaveAttribute("aria-sort", "ascending");
    expect(header("Next Hearing")).not.toHaveAttribute("aria-sort");
    await userEvent.click(within(header("Score")).getByRole("button"));
    expect(header("Score")).toHaveAttribute("aria-sort", "descending");
    expect(header("Name")).not.toHaveAttribute("aria-sort");
    expect(header("Note")).not.toHaveAttribute("aria-sort");
  });

  it("hides the arrow from screen readers and names the column and direction in a live region", async () => {
    render(<Table />);
    const button = within(header("Next Hearing")).getByRole("button");
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    await userEvent.click(button);
    expect(screen.getByRole("status")).toHaveTextContent("Sorted by Next Hearing, Earliest First");
    expect(screen.getByText("Sorted by Next Hearing, Earliest First", { selector: "[data-ui='order-line']" })).toBeInTheDocument();
  });

  it("keeps focus on the header button after a sort", async () => {
    render(<Table />);
    const button = within(header("Score")).getByRole("button");
    await userEvent.click(button);
    expect(within(header("Score")).getByRole("button")).toHaveFocus();
  });

  it("SortHeader works in a hand-written table", async () => {
    const onSort = vi.fn();
    render(
      <table>
        <thead>
          <tr>
            <SortHeader sortKey="rows" type="number" sort={null} onSort={onSort}>
              Rows
            </SortHeader>
          </tr>
        </thead>
      </table>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Rows" }));
    expect(onSort).toHaveBeenCalledWith({ key: "rows", dir: "desc" });
  });
});

describe("the phone Sort By select (decision 33)", () => {
  it("shows when the table is drawn as cards, lists Default and every sortable column, and drives the same sort", async () => {
    phone(true);
    render(<Table />);
    const select = await screen.findByRole("combobox", { name: "Sort By" });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Default (Name, A to Z)", "Name", "Next Hearing", "Score"]);
    expect(screen.queryByRole("button", { name: /First|A to Z/ })).toBeNull(); // Default hides the direction button
    await userEvent.selectOptions(select, "next");
    expect(names()).toEqual(["Das", "Bora", "Ahmed"]);
    const dir = screen.getByRole("button", { name: "Earliest First" });
    await userEvent.click(dir);
    expect(names()).toEqual(["Bora", "Das", "Ahmed"]);
    expect(screen.getByRole("button", { name: "Latest First" })).toBeInTheDocument();
    // the header shows the same state
    expect(header("Next Hearing")).toHaveAttribute("aria-sort", "descending");
  });

  it("is not drawn while the table fits", () => {
    render(<Table />);
    expect(screen.queryByRole("combobox", { name: "Sort By" })).toBeNull();
  });

  it("Default Order on the order line returns to the default", async () => {
    render(<Table initial={{ key: "score", dir: "desc" }} />);
    expect(screen.getByText(/Sorted by Score, Highest First/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Default Order" }));
    expect(screen.getByText("Order: Name, A to Z")).toBeInTheDocument();
  });
});

/** A list keeping its search and sort in the address. */
function UrlList({ params }: { params: Params }) {
  const state = useListState({ mode: "url", params, sortKeys: ["case_no", "next_hearing"] });
  return (
    <>
      <output data-testid="sort">{state.sort ? `${state.sort.key} ${state.sort.dir}` : "default"}</output>
      <button type="button" onClick={() => state.setSort({ key: "case_no", dir: "asc" })}>
        Sort
      </button>
    </>
  );
}

describe("the address (decisions 5 and 35)", () => {
  it("writes sort and dir with router.replace, drops offset, and reads them back; Back restores the earlier sort", async () => {
    const { rerender } = render(<UrlList params={{ q: "ram", offset: "50" }} />);
    expect(screen.getByTestId("sort")).toHaveTextContent("default");
    await userEvent.click(screen.getByRole("button", { name: "Sort" }));
    expect(nav.replace).toHaveBeenCalledWith("/inbox/department?q=ram&sort=case_no&dir=asc");
    expect(nav.push).not.toHaveBeenCalled();
    rerender(<UrlList params={{ q: "ram", sort: "case_no", dir: "asc" }} />);
    expect(screen.getByTestId("sort")).toHaveTextContent("case_no asc");
    // Back: the address holds the earlier sort again
    rerender(<UrlList params={{ q: "ram", sort: "next_hearing", dir: "desc" }} />);
    expect(screen.getByTestId("sort")).toHaveTextContent("next_hearing desc");
  });

  it("an unknown key in the address gives the default order, quietly", () => {
    render(<UrlList params={{ sort: "raw_sql", dir: "asc" }} />);
    expect(screen.getByTestId("sort")).toHaveTextContent("default");
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("Clear All keeps the sort: a sort is not a filter", () => {
    expect(clearAllUpdates({ q: "ram", year: "2025", sort: "case_no", dir: "asc", offset: "50", department: "EDU" }, "department")).toEqual({
      q: undefined,
      year: undefined,
      offset: undefined,
    });
  });
});
