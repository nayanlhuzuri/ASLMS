import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CodeBlock, CopyButton, DataTable } from "./data";

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
