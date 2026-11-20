import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InsightsCharts } from "@/components/insights/InsightsCharts";
import { overview } from "@/test/insightsFixtures";
import { callsOf, resetRecharts } from "@/test/rechartsMock";
import { renderWithClient } from "@/test/render";

import { GroupedBarChart, HBarChart, StackedBarChart } from "./insightCharts";

vi.mock("recharts", async () => (await import("@/test/rechartsMock")).rechartsModule);

const SERIES = [
  { key: "claimed", label: "Claimed" },
  { key: "likely", label: "Recommended, Not Claimed" },
  { key: "named", label: "Named in the Cause Title or by Counsel Code" },
];

function motion(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({ matches: reduced, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn() })),
  );
}

beforeEach(() => {
  resetRecharts();
  document.documentElement.style.setProperty("--chart-1", "#22386a");
  document.documentElement.style.setProperty("--chart-2", "#3c5a94");
  document.documentElement.style.setProperty("--chart-selected", "#f28c28");
  document.documentElement.style.setProperty("--red", "#b42318");
});

afterEach(() => {
  document.documentElement.removeAttribute("style");
});

describe("the Insights chart kit (design state-insights, decision 31)", () => {
  it("View As Table carries the same numbers, and each row's filter button sets that filter", async () => {
    const onChange = vi.fn();
    renderWithClient(<InsightsCharts data={overview()} params={{}} onChange={onChange} />);
    const card = screen.getByRole("heading", { name: "Next Hearing" }).closest("section")!;
    await userEvent.click(within(card).getByRole("button", { name: "View As Table" }));
    const table = within(card).getByRole("table", { name: "Next Hearing" });
    const today = within(table).getByRole("rowheader", { name: "Today" }).closest("tr")!;
    expect(within(today).getByText("4")).toBeInTheDocument();
    expect(within(table).getByRole("rowheader", { name: "Date Passed" }).closest("tr")).toHaveTextContent("40");
    await userEvent.click(within(today).getByRole("button", { name: "Show only Today" }));
    expect(onChange).toHaveBeenCalledWith({ next: "today" });
    // back to the chart
    await userEvent.click(within(card).getByRole("button", { name: "View As Chart" }));
    expect(within(card).getByRole("img", { name: /^Next Hearing: Today 4, Tomorrow 2/ })).toBeInTheDocument();
  });

  it("the selected row's button removes the filter, and the selected label carries a tick", async () => {
    const onChange = vi.fn();
    renderWithClient(<InsightsCharts data={overview()} params={{ next: "today", kind: "wp" }} onChange={onChange} />);
    const card = screen.getByRole("heading", { name: "Next Hearing" }).closest("section")!;
    await userEvent.click(within(card).getByRole("button", { name: "View As Table" }));
    const row = within(card).getByRole("rowheader", { name: "✓ Today" }).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Remove the filter Today" }));
    expect(onChange).toHaveBeenCalledWith({ kind: "wp" });
  });

  it("reduced motion turns the animation off; otherwise the bars animate", () => {
    motion(true);
    renderWithClient(<HBarChart title="Posts" data={[{ key: "a", label: "A", count: 1 }]} />);
    expect(callsOf("Bar").at(-1)!.isAnimationActive).toBe(false);
    expect(screen.getByRole("img", { name: "Posts: A 1" })).toHaveAttribute("data-motion", "off");
    resetRecharts();
    motion(false);
    renderWithClient(<HBarChart title="Subjects" data={[{ key: "a", label: "A", count: 1 }]} />);
    expect(callsOf("Bar").at(-1)!.isAnimationActive).toBe(true);
  });

  it("colours come from the tokens: the series colour, the selected colour and the hearing band colour", () => {
    renderWithClient(
      <HBarChart
        title="Next Hearing"
        data={[
          { key: "today", label: "Today", count: 4 },
          { key: "later", label: "Later", count: 9 },
        ]}
        selected="later"
        colourOf={(key, t) => (key === "today" ? t.strong : t.series[0]!)}
      />,
    );
    const fills = callsOf("Cell").map((p) => p.fill);
    expect(fills).toEqual(["#b42318", "#f28c28"]);
  });

  it("the chart kit names no colour literal (the colour guard)", () => {
    const source = readFileSync(join(process.cwd(), "src", "components", "ui", "insightCharts.tsx"), "utf-8");
    expect(source).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(source).not.toMatch(/\b(rgba?|hsla?)\(/i);
  });

  it("the grouped bars are never stacked; the kind × age bars are", () => {
    const rows = [{ key: "EDU", label: "School Education", values: { claimed: 5, likely: 40, named: 20 } }];
    renderWithClient(<GroupedBarChart title="By Department" rows={rows} series={SERIES} />);
    const grouped = callsOf("Bar");
    expect(grouped).toHaveLength(3);
    for (const bar of grouped) expect(bar.stackId).toBeUndefined();
    resetRecharts();
    renderWithClient(<StackedBarChart title="Kinds" rows={rows} series={SERIES} />);
    const stacked = callsOf("Bar");
    expect(new Set(stacked.map((b) => b.stackId))).toEqual(new Set(["stack"]));
  });

  it("the selected bar has its tick label and the selected colour", () => {
    renderWithClient(
      <HBarChart
        title="Posts"
        data={[
          { key: "secretary", label: "Secretary", count: 3 },
          { key: "director", label: "Director", count: 1 },
        ]}
        selected="director"
      />,
    );
    const data = callsOf("BarChart").at(-1)!.data as { axis: string }[];
    expect(data.map((d) => d.axis)).toEqual(["Secretary", "✓ Director"]);
    expect(callsOf("Cell").map((c) => c.fill)).toEqual(["#22386a", "#f28c28"]);
  });

  it("a click on a bar sets its key", () => {
    const onSelect = vi.fn();
    renderWithClient(<HBarChart title="Posts" data={[{ key: "secretary", label: "Secretary", count: 3 }]} onSelect={onSelect} />);
    const click = callsOf("Bar").at(-1)!.onClick as (item: { payload: { key: string } }) => void;
    click({ payload: { key: "secretary" } });
    expect(onSelect).toHaveBeenCalledWith("secretary");
  });

  it("the department bands are never added together: the table has one button per band and no total", async () => {
    const onChange = vi.fn();
    renderWithClient(<InsightsCharts data={overview()} params={{}} onChange={onChange} />);
    const card = screen.getByRole("heading", { name: "By Department" }).closest("section")!;
    await userEvent.click(within(card).getByRole("button", { name: "View As Table" }));
    const table = within(card).getByRole("table", { name: "By Department" });
    expect(within(table).queryByRole("columnheader", { name: /total/i })).toBeNull();
    await userEvent.click(within(table).getByRole("button", { name: "Show only School Education · Recommended, Not Claimed" }));
    expect(onChange).toHaveBeenCalledWith({ dept: "EDU", band: "likely" });
  });

  it("a holder sets the holder and the overdue action together", async () => {
    const onChange = vi.fn();
    renderWithClient(<InsightsCharts data={overview()} params={{}} onChange={onChange} />);
    const card = screen.getByRole("heading", { name: "Who Is Holding Cases" }).closest("section")!;
    await userEvent.click(within(card).getByRole("button", { name: "View As Table" }));
    await userEvent.click(within(card).getByRole("button", { name: "Show only Secondary Education" }));
    expect(onChange).toHaveBeenCalledWith({ holder: "EDU-DSE", action: "overdue" });
  });

  it("the department view shows By Unit and no scorecard", () => {
    renderWithClient(
      <InsightsCharts
        data={overview({
          scope: { kind: "department", department: { code: "EDU", name: "School Education" } },
          departments: null,
          units: [{ code: "none", name: "Not Yet Assigned to a Unit", claimed: 5 }],
          department_bands: { claimed: 5, likely: 40, named: 20 },
          accountability: { ...overview().accountability, scorecard: null },
        })}
        params={{ scope: "department" }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "By Unit" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "By Department" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Department Scorecard" })).toBeNull();
  });
});
