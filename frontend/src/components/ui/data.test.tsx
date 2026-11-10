import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CodeBlock, CopyButton, DataTable, ItemHead, Lead } from "./data";

const CSS = readFileSync(join(process.cwd(), "src", "components", "ui", "data.module.css"), "utf-8");

function rule(selector: string): string {
  const at = CSS.indexOf(`${selector} {`);
  return CSS.slice(at, CSS.indexOf("}", at));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("CodeBlock and CopyButton (design system-health-inspector, decision 14)", () => {
  it("scrolls sideways inside itself, never the page", () => {
    render(<CodeBlock label="The Plain String">{"est_code=GAHC01|causelist_date=2026-10-20"}</CodeBlock>);
    const pre = screen.getByLabelText("The Plain String");
    expect(pre.tagName).toBe("PRE");
    expect(pre).toHaveAttribute("tabindex", "0"); // reachable by keyboard to scroll
    // one of the three places the browser check lets scroll sideways (owner, 28 Oct 2026)
    expect(pre).toHaveAttribute("data-scroll-x");
    expect(pre).toHaveTextContent("est_code=GAHC01|causelist_date=2026-10-20");
    expect(rule(".code")).toMatch(/overflow-x: auto/);
    expect(rule(".code")).toMatch(/white-space: pre/);
    expect(rule(".codeBlock")).toMatch(/max-width: 100%/);
    expect(rule(".codeBlock")).toMatch(/min-width: 0/);
  });

  it("its copy button copies the text and announces Copied to screen readers", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<CodeBlock label="cURL Template">{"curl -G 'https://x'"}</CodeBlock>);
    const figure = screen.getByLabelText("cURL Template").closest("figure")!;
    await userEvent.click(within(figure).getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("curl -G 'https://x'");
    const status = within(figure).getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent("Copied");
  });

  it("a refused clipboard says so", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => Promise.reject(new Error("no"))) } });
    render(<CopyButton text="x" />);
    await userEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(screen.getByRole("status")).toHaveTextContent("Could not copy");
  });
});

describe("DataTable measures when its data changes (design followups-oct, decision 23)", () => {
  type Row = { id: string; name: string };
  const COLUMNS = [
    { key: "id", header: "Id", cell: (r: Row) => r.id },
    { key: "name", header: "Name", cell: (r: Row) => r.name },
  ];

  function measures(spy: ReturnType<typeof vi.spyOn>): number {
    return spy.mock.calls.filter((c: unknown[]) => c[0] === "data-stacked").length;
  }

  it("fitTable runs once for unchanged rows across re-renders", () => {
    const spy = vi.spyOn(Element.prototype, "removeAttribute");
    const rows: Row[] = [{ id: "1", name: "first" }];
    const view = render(<DataTable columns={COLUMNS} rows={rows} rowKey={(r) => r.id} caption="Rows" />);
    expect(measures(spy)).toBe(1);
    view.rerender(<DataTable columns={COLUMNS} rows={rows} rowKey={(r) => r.id} caption="Rows" />);
    view.rerender(<DataTable columns={[...COLUMNS]} rows={rows} rowKey={(r) => r.id} caption="Rows" />);
    expect(measures(spy)).toBe(1); // a new columns array with the same keys is no change
    spy.mockRestore();
  });

  it("fitTable runs again when rows change", () => {
    const spy = vi.spyOn(Element.prototype, "removeAttribute");
    const view = render(<DataTable columns={COLUMNS} rows={[{ id: "1", name: "a" }]} rowKey={(r) => r.id} />);
    expect(measures(spy)).toBe(1);
    // the same count with longer text: still measured again
    view.rerender(<DataTable columns={COLUMNS} rows={[{ id: "1", name: "a much longer name" }]} rowKey={(r) => r.id} />);
    expect(measures(spy)).toBe(2);
    view.rerender(<DataTable columns={COLUMNS.slice(0, 1)} rows={[{ id: "1", name: "a much longer name" }]} rowKey={(r) => r.id} />);
    expect(measures(spy)).toBe(3);
    spy.mockRestore();
  });
});

/** The declarations of one rule, normalised, from `css` (the first `selector {` at the start of a line or indented). */
function decls(css: string, selector: string): string {
  const lines = css.split("\n");
  const index = lines.findIndex((l) => l.trim() === `${selector} {`);
  if (index < 0) throw new Error(`no rule ${selector}`);
  const at = lines.slice(0, index).join("\n").length;
  const open = css.indexOf("{", at);
  return css
    .slice(open + 1, css.indexOf("}", open))
    .split(";")
    .map((d) => d.trim())
    .filter(Boolean)
    .join("; ");
}

const PHONE = CSS.slice(CSS.indexOf("@media (max-width: 819px)"), CSS.indexOf(".dataWrap[data-stacked] {"));
const STACKED = CSS.slice(CSS.indexOf(".dataWrap[data-stacked] {"), CSS.indexOf(".pagination {"));

describe("captions and card rows (design portal-ui-kit-fixes, decisions 1, 6, 8 and 9)", () => {
  it("the caption is inset like the cells; the hidden caption keeps no padding", () => {
    expect(decls(CSS, ".table caption")).toMatch(/padding: var\(--s3\) var\(--s4\) var\(--s2\)/);
    expect(rule(".dataWrap[data-stacked] .dataTable caption.srCaption")).toMatch(/padding: 0;/);
  });

  it.each([
    ["phone", PHONE, ""],
    ["data-stacked", STACKED, ".dataWrap[data-stacked] "],
  ])("in the %s block a card cell is a two-column grid with left-aligned values", (_name, block, prefix) => {
    const td = decls(block, `${prefix}.dataTable td`);
    expect(td).toMatch(/display: grid/);
    expect(td).toMatch(/grid-template-columns: var\(--card-label-w\) minmax\(0, 1fr\)/);
    expect(td).toMatch(/text-align: left/);
    expect(td).toMatch(/overflow-wrap: break-word/);
    expect(td).not.toMatch(/justify-content: space-between/);
    expect(td).not.toMatch(/overflow-wrap: anywhere/);
    expect(block).toContain(`${prefix}.dataTable td:has(> .cellValue:empty),`);
    expect(block).toContain(`${prefix}.dataTable td:has(> .cellValue > :only-child:empty) {`);
  });

  it("the phone block and the data-stacked block carry identical declarations", () => {
    for (const sel of [
      ".dataTable td",
      ".dataTable td.num",
      ".dataTable td > *",
      ".dataTable td > .cellValue",
      ".dataTable td::before",
      ".dataTable td:has(> .cellValue > :only-child:empty)",
      ".dataTable td.primaryCell::before",
      ".dataTable td.actionsCell",
      ".dataTable td.actionsCell::before",
    ]) {
      expect(decls(STACKED, `.dataWrap[data-stacked] ${sel}`), sel).toBe(decls(PHONE, sel));
    }
  });

  type Row = { id: string; v: string | null };
  const COLUMNS = [
    { key: "id", header: "Id", primary: true, cell: (r: Row) => r.id },
    { key: "none", header: "Status", cell: (r: Row) => (r.v === null ? null : r.v) },
    { key: "lead", header: "State", cell: () => <Lead>{null}</Lead> },
    { key: "dash", header: "Due", cell: () => "—" },
    { key: "button", header: "Actions", cell: () => <button type="button">Open</button> },
  ];

  it("a cell returning null is an empty value box and an empty Lead is one empty child; a dash or a button is not empty", () => {
    render(<DataTable columns={COLUMNS} rows={[{ id: "1", v: null }]} rowKey={(r) => r.id} />);
    const cells = screen.getAllByRole("cell");
    const value = (label: string) => cells.find((c) => c.getAttribute("data-label") === label)!.firstElementChild!;
    expect(value("Status").childNodes.length).toBe(0);
    expect(value("State").children.length).toBe(1);
    expect(value("State").firstElementChild!.childNodes.length).toBe(0);
    expect(value("Due").textContent).toBe("—");
    expect(value("Actions").querySelector("button")).not.toBeNull();
  });
});

describe("ItemHead (design portal-ui-kit-fixes, decision 10)", () => {
  it("puts the title first, then the meta, then the badges, with no Lead", () => {
    const { container } = render(
      <ItemHead title={<strong>Hearing Listed</strong>} meta={<span className="muted">Open</span>} badges={<span>High</span>} />,
    );
    const head = container.querySelector("[data-ui='item-head']")!;
    expect(head).not.toBeNull();
    expect(head.textContent).toBe("Hearing ListedOpenHigh");
    expect(head.firstElementChild!.firstElementChild!.tagName).toBe("STRONG");
    expect(head.querySelector("[data-lead]")).toBeNull();
    expect(rule(".itemBadges")).toMatch(/flex: none/);
    expect(rule(".itemBadges")).toMatch(/margin-left: auto/);
    expect(rule(".itemTitle")).toMatch(/flex: 1 1 auto/);
  });

  it("leaves the badges slot out when there are none", () => {
    const { container } = render(<ItemHead title="Note" />);
    expect(container.querySelector("[data-ui='item-head']")!.children.length).toBe(1);
  });
});

describe("an actions column (design portal-ui-kit-fixes, build deviations)", () => {
  it("has no card label and runs the card's full width", () => {
    type Row = { id: string };
    render(
      <DataTable
        columns={[
          { key: "id", header: "Id", primary: true, cell: (r: Row) => r.id },
          { key: "go", header: "Actions", actions: true, cell: () => <button type="button">Stop Using Everything</button> },
        ]}
        rows={[{ id: "1" }]}
        rowKey={(r) => r.id}
      />,
    );
    const cell = screen.getByRole("button", { name: "Stop Using Everything" }).closest("td")!;
    expect(cell).not.toHaveAttribute("data-label");
    expect(decls(PHONE, ".dataTable td.actionsCell")).toBe("display: block");
    expect(decls(PHONE, ".dataTable td.actionsCell::before")).toBe("content: none");
  });
});
