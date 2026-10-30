import { act, fireEvent, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetNav } from "@/test/nav";
import { renderWithClient } from "@/test/render";

import {
  Badge,
  ProgressBar,
  ProgressLegend,
  ScrollBox,
  TabToolbar,
  Button,
  CheckField,
  Chip,
  Collapsible,
  controlClass,
  DataTable,
  DateChip,
  Dialog,
  EmptyState,
  FilterCard,
  FilterChip,
  Lead,
  LeadIcon,
  ListRow,
  Loading,
  Menu,
  Meter,
  Modal,
  PageHeader,
  ScoreBadge,
  SegmentedSwitch,
  SelectField,
  SidePanel,
  Stepper,
  Tabs,
  TextArea,
  TextField,
} from "./index";

beforeEach(() => {
  resetNav("/");
});

describe("one control height (design portal-ui-redesign, decision 14)", () => {
  it("every button, input and select renders at the 36 px class; the sm button does not", () => {
    renderWithClient(
      <>
        <Button>Primary</Button>
        <Button variant="secondary">Secondary</Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger">Danger</Button>
        <Button size="sm">Print</Button>
        <TextField label="Name" />
        <SelectField label="Kind" options={[{ value: "a", label: "A" }]} />
        <TextArea label="Remark" />
      </>,
    );
    for (const name of ["Primary", "Secondary", "Ghost", "Danger"]) {
      expect(screen.getByRole("button", { name })).toHaveClass(controlClass);
    }
    expect(screen.getByRole("button", { name: "Print" })).not.toHaveClass(controlClass);
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveClass(controlClass);
    expect(screen.getByRole("combobox", { name: "Kind" })).toHaveClass(controlClass);
    expect(screen.getByRole("textbox", { name: "Remark" })).not.toHaveClass(controlClass);
    expect(screen.getByRole("button", { name: "Primary" })).toHaveAttribute("data-variant", "primary");
  });
});

describe("Tabs", () => {
  it("marks the current tab, places the underline and shows counts", () => {
    renderWithClient(
      <Tabs
        label="Case Sections"
        items={[
          { href: "/a", label: "Overview", active: false },
          { href: "/b", label: "Orders", active: true, count: 4 },
        ]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Case Sections" });
    expect(within(nav).getByRole("link", { name: "Orders (4)" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(screen.getByTestId("tab-ink")).toBeInTheDocument();
  });

  it("puts the more group in a menu whose button names the current tab", async () => {
    renderWithClient(
      <Tabs
        label="Case Sections"
        items={[{ href: "/a", label: "Overview", active: false }]}
        more={[
          { href: "/p", label: "Parties", active: true },
          { href: "/l", label: "Linked Cases", active: false },
        ]}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Parties" });
    await userEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Parties" })).toHaveAttribute("aria-current", "page");
    expect(within(menu).getByRole("menuitem", { name: "Linked Cases" })).toHaveAttribute("href", "/l");
  });

  it("the more button reads More when none of its tabs is current", () => {
    renderWithClient(
      <Tabs label="Case Sections" items={[{ href: "/a", label: "Overview", active: true }]} more={[{ href: "/p", label: "Parties", active: false }]} />,
    );
    expect(screen.getByRole("button", { name: "More" })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Tabs follow a tab's own width (design portal-ui-polish, decision 1)", () => {
  it("tab underline re-measures when a tab's width changes", () => {
    const observers: { cb: ResizeObserverCallback; els: Element[] }[] = [];
    class FakeResizeObserver {
      els: Element[] = [];
      constructor(cb: ResizeObserverCallback) {
        observers.push({ cb, els: this.els });
      }
      observe(el: Element) {
        this.els.push(el);
      }
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    try {
      renderWithClient(
        <Tabs
          label="Case Sections"
          items={[
            { href: "/a", label: "Overview", active: false },
            { href: "/b", label: "Orders", active: true },
          ]}
        />,
      );
      const tab = screen.getByRole("link", { name: "Orders" });
      const nav = screen.getByRole("navigation", { name: "Case Sections" });
      expect(nav).toHaveAttribute("data-scroll-x");
      const watcher = observers.find((o) => o.els.includes(tab));
      expect(watcher).toBeDefined();
      expect(watcher!.els).toContain(nav);
      Object.defineProperty(tab, "offsetWidth", { configurable: true, value: 120 });
      Object.defineProperty(tab, "offsetLeft", { configurable: true, value: 90 });
      act(() => watcher!.cb([], watcher as unknown as ResizeObserver));
      expect(screen.getByTestId("tab-ink")).toHaveStyle({ left: "90px", width: "120px" });
      Object.defineProperty(tab, "offsetWidth", { configurable: true, value: 150 });
      act(() => watcher!.cb([], watcher as unknown as ResizeObserver));
      expect(screen.getByTestId("tab-ink")).toHaveStyle({ width: "150px" });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("Menu", () => {
  it("opens and closes by keyboard, with arrow keys between the items", async () => {
    const onSelect = vi.fn();
    renderWithClient(
      <Menu
        label="More Actions"
        items={[
          { key: "recall", label: "Recall", onSelect },
          { key: "stage", label: "Set Stage" },
        ]}
      />,
    );
    const button = screen.getByRole("button", { name: "More Actions" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Recall" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Set Stage" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Recall" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("Menu in a portal (design case-inbox-simplify, decisions 22 to 25)", () => {
  const ITEMS = [
    { key: "a", label: "Parties", href: "/p" },
    { key: "b", label: "Linked Cases", href: "/l" },
    { key: "c", label: "Details", href: "/d" },
  ];
  const rect = (top: number, left: number, width = 80, height = 32) =>
    ({ top, bottom: top + height, left, right: left + width, width, height, x: left, y: top, toJSON: () => ({}) }) as DOMRect;

  function place(button: HTMLElement, r: DOMRect) {
    button.getBoundingClientRect = () => r;
  }

  function sized<T>(height: number, width: number, run: () => T): T {
    const h = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetHeight");
    const w = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth");
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => height });
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => width });
    try {
      return run();
    } finally {
      if (h) Object.defineProperty(HTMLElement.prototype, "offsetHeight", h);
      if (w) Object.defineProperty(HTMLElement.prototype, "offsetWidth", w);
    }
  }

  it("the list mounts in document.body, position fixed, its top the button's bottom plus 4", async () => {
    const { container } = renderWithClient(<Menu label="More" items={ITEMS} align="start" />);
    const button = screen.getByRole("button", { name: "More" });
    place(button, rect(100, 50));
    await userEvent.click(button);
    const menu = screen.getByRole("menu");
    expect(container.contains(menu)).toBe(false);
    expect(menu.parentElement).toBe(document.body);
    expect(menu.style.position).toBe("fixed");
    expect(menu.style.top).toBe("136px");
    expect(menu.style.left).toBe("50px");
  });

  it("opens above when the room below is short and the room above larger; stays 8 px inside the right edge", () => {
    sized(200, 220, () => {
      renderWithClient(<Menu label="More" items={ITEMS} align="start" />);
      const button = screen.getByRole("button", { name: "More" });
      place(button, rect(window.innerHeight - 40, window.innerWidth - 60, 50));
      fireEvent.click(button);
      const menu = screen.getByRole("menu");
      expect(menu.style.top).toBe("");
      expect(menu.style.bottom).toBe(`${40 + 4}px`);
      expect(parseFloat(menu.style.left) + 220).toBeLessThanOrEqual(window.innerWidth - 8);
    });
  });

  it("inside a [role='dialog'] the list mounts in the dialog", async () => {
    renderWithClient(
      <div role="dialog" aria-label="Panel">
        <Menu label="More" items={ITEMS} />
      </div>,
    );
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("menu").parentElement).toBe(screen.getByRole("dialog", { name: "Panel" }));
  });

  it("keyboard: ArrowDown opens on the first item; Arrow, Home and End move; Escape returns the focus; Tab closes", async () => {
    renderWithClient(<Menu label="More" items={ITEMS} />);
    const button = screen.getByRole("button", { name: "More" });
    button.focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Parties" })).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(screen.getByRole("menuitem", { name: "Details" })).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(screen.getByRole("menuitem", { name: "Parties" })).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("menuitem", { name: "Details" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Tab}");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("a mousedown on an item does not close before the click; an outside mousedown closes", async () => {
    const onSelect = vi.fn();
    renderWithClient(
      <>
        <p>outside</p>
        <Menu label="More" items={[{ key: "x", label: "Recall", onSelect }]} />
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.mouseDown(screen.getByRole("menuitem", { name: "Recall" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Recall" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("a scroll on an ancestor that moves the button closes; a scroll inside the list or a late one that moves nothing does not; a resize closes", async () => {
    renderWithClient(
      <div data-testid="scroller">
        <Menu label="More" items={ITEMS} />
      </div>,
    );
    const button = screen.getByRole("button", { name: "More" });
    place(button, rect(100, 50));
    await userEvent.click(button);
    fireEvent.scroll(screen.getByRole("menu"));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    // the tab bar's late scroll event from bringing the button into view as it was pressed: the button stays put
    fireEvent.scroll(screen.getByTestId("scroller"));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    // the page scrolls: the button moves away from where the list was placed
    place(button, rect(60, 50));
    fireEvent.scroll(screen.getByTestId("scroller"));
    expect(screen.queryByRole("menu")).toBeNull();
    place(button, rect(100, 50));
    await userEvent.click(button);
    act(() => {
      window.dispatchEvent(new Event("resize"));
    });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("Tabs with more: every More item is rendered, none inside the nav", async () => {
    renderWithClient(
      <Tabs
        label="Case Sections"
        items={[{ href: "/a", label: "Overview", active: true }]}
        more={[
          { href: "/p", label: "Parties", active: false },
          { href: "/l", label: "Linked Cases", active: false },
          { href: "/j", label: "Journey and Stage", active: false },
          { href: "/al", label: "Alerts", active: false },
          { href: "/d", label: "Details", active: false },
        ]}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    const nav = screen.getByRole("navigation", { name: "Case Sections" });
    const items = screen.getAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Parties", "Linked Cases", "Journey and Stage", "Alerts", "Details"]);
    for (const item of items) expect(nav.contains(item)).toBe(false);
  });

  it("the tab bar draws the focus ring inside the tab (a negative outline-offset)", () => {
    const css = readFileSync(join(process.cwd(), "src", "components", "ui", "layout.module.css"), "utf-8");
    const rule = /\.tabs \.tab:focus-visible\s*\{([^}]*)\}/.exec(css);
    expect(rule).not.toBeNull();
    expect(rule![1]).toMatch(/outline-offset:\s*-\d+px/);
    expect(rule![1]).toMatch(/box-shadow:\s*inset/);
  });
});

describe("Collapsible", () => {
  it("toggles aria-expanded and mounts its body on first opening", async () => {
    renderWithClient(
      <Collapsible summary="Show Parties, Advocates and Acts">
        <p>Petitioner A</p>
      </Collapsible>,
    );
    const button = screen.getByRole("button", { name: "Show Parties, Advocates and Acts" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Petitioner A")).toBeNull();
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Petitioner A")).toBeInTheDocument();
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
  });
});

type Overlay = "dialog" | "modal" | "panel";

function OverlayHarness({ kind }: { kind: Overlay }) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const body: ReactNode = (
    <>
      <input aria-label="First field" />
      <button type="button">Last button</button>
    </>
  );
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open it
      </button>
      {kind === "dialog" ? (
        <Dialog open={open} title="A dialog" onClose={close}>
          {body}
        </Dialog>
      ) : kind === "modal" ? (
        <Modal open={open} title="A modal" onClose={close} footer={<button type="button">Footer action</button>}>
          {body}
        </Modal>
      ) : (
        <SidePanel open={open} title="A panel" onClose={close}>
          {body}
        </SidePanel>
      )}
    </>
  );
}

describe.each<Overlay>(["dialog", "modal", "panel"])("%s (the shared overlay behaviour)", (kind) => {
  it("traps focus, closes on Escape and returns focus", async () => {
    renderWithClient(<OverlayHarness kind={kind} />);
    const opener = screen.getByRole("button", { name: "Open it" });
    await userEvent.click(opener);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");
    for (let i = 0; i < 6; i += 1) {
      await userEvent.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
    await userEvent.tab({ shift: true });
    expect(dialog.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });
});

describe("an overlay's first focus (design portal-ui-polish, decision 3)", () => {
  it("overlay focuses the first field, not Close", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open it
          </button>
          <Dialog open={open} title="New User" onClose={() => setOpen(false)} footer={<Button>Save</Button>}>
            <input type="hidden" name="token" />
            <p>
              <a href="/help">Help</a>
            </p>
            <TextField label="E-mail" />
          </Dialog>
        </>
      );
    }
    renderWithClient(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    expect(screen.getByRole("textbox", { name: "E-mail" })).toHaveFocus();
  });

  it("overlay without fields focuses the body's first control", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open it
          </button>
          <Modal open={open} title="A case" onClose={() => setOpen(false)} footer={<Button>Claim</Button>}>
            <p>Some facts</p>
            <button type="button">Parties</button>
          </Modal>
        </>
      );
    }
    renderWithClient(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    expect(screen.getByRole("button", { name: "Parties" })).toHaveFocus();
  });

  it("an overlay with nothing in the body focuses the footer's first control, and Close only when alone", async () => {
    function Harness({ footer }: { footer: boolean }) {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open it
          </button>
          <SidePanel open={open} title="Facts" onClose={() => setOpen(false)} footer={footer ? <Button>Done</Button> : undefined}>
            <p>Only words</p>
          </SidePanel>
        </>
      );
    }
    const first = renderWithClient(<Harness footer />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    expect(screen.getByRole("button", { name: "Done" })).toHaveFocus();
    first.unmount();
    renderWithClient(<Harness footer={false} />);
    await userEvent.click(screen.getByRole("button", { name: "Open it" }));
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Close" })).toHaveFocus();
  });

  it("Dialog wide adds the wide class", () => {
    const { rerender } = renderWithClient(
      <Dialog open title="Plain" onClose={() => {}}>
        <p>Body</p>
      </Dialog>,
    );
    const plain = screen.getByRole("dialog").className;
    expect(plain).not.toMatch(/wide/);
    rerender(
      <Dialog open title="Wide" onClose={() => {}} wide>
        <p>Body</p>
      </Dialog>,
    );
    expect(screen.getByRole("dialog").className).toMatch(/wide/);
  });
});

describe("Button carries data-ui and data-size (design portal-ui-polish, decision 21)", () => {
  it("Button carries data-ui and data-size", () => {
    renderWithClient(
      <>
        <Button>Save</Button>
        <Button size="sm" variant="secondary">
          Edit
        </Button>
        <Button variant="link">More</Button>
        <TextField label="Name" />
        <SelectField label="Kind" options={[{ value: "a", label: "A" }]} />
        <TextArea label="Remark" />
      </>,
    );
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toHaveAttribute("data-ui", "button");
    expect(save).toHaveAttribute("data-size", "md");
    expect(screen.getByRole("button", { name: "Edit" })).toHaveAttribute("data-size", "sm");
    expect(screen.getByRole("button", { name: "More" })).not.toHaveAttribute("data-size");
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveAttribute("data-ui", "field");
    expect(screen.getByRole("combobox", { name: "Kind" })).toHaveAttribute("data-ui", "field");
    expect(screen.getByRole("textbox", { name: "Remark" })).toHaveAttribute("data-ui", "field");
  });
});

describe("DataTable (decision 18)", () => {
  interface Row {
    id: string;
    no: string;
    stage: string;
    court: string;
  }
  const rows: Row[] = [
    { id: "1", no: "WP(C)/1/2026", stage: "Reply filed", court: "Court 3" },
    { id: "2", no: "WP(C)/2/2026", stage: "Notice", court: "Court 5" },
  ];

  it("labels every cell for the phone cards, leaves out hideOnPhone columns and opens a row by Enter", async () => {
    const open = vi.fn();
    renderWithClient(
      <DataTable
        caption="Cases"
        rows={rows}
        rowKey={(r) => r.id}
        onRowClick={open}
        rowLabel={(r) => r.no}
        columns={[
          { key: "no", header: "Case", cell: (r) => r.no, primary: true },
          { key: "stage", header: "Stage", cell: (r) => r.stage, width: "var(--lead-w)" },
          { key: "court", header: "Court", cell: (r) => r.court, hideOnPhone: true },
        ]}
      />,
    );
    const table = screen.getByRole("table", { name: "Cases" });
    expect(within(table).getByRole("columnheader", { name: "Stage" })).toHaveStyle({ width: "var(--lead-w)" });
    const cells = within(table).getAllByRole("cell");
    expect(cells).toHaveLength(6);
    const stageCells = cells.filter((c) => c.textContent === "Reply filed" || c.textContent === "Notice");
    for (const c of stageCells) expect(c).toHaveAttribute("data-label", "Stage");
    for (const c of cells.filter((c) => c.textContent?.startsWith("Court"))) expect(c).not.toHaveAttribute("data-label");
    const row = screen.getByRole("row", { name: "WP(C)/2/2026" });
    row.focus();
    await userEvent.keyboard("{Enter}");
    expect(open).toHaveBeenCalledWith(rows[1]);
    await userEvent.click(screen.getByText("WP(C)/1/2026"));
    expect(open).toHaveBeenCalledWith(rows[0]);
  });

  it("becomes cards on a wide screen when its columns cannot fit the box, and a table again when they can (review of 21 Oct 2026)", () => {
    const observers: { cb: ResizeObserverCallback; els: Element[] }[] = [];
    class FakeResizeObserver {
      els: Element[] = [];
      constructor(cb: ResizeObserverCallback) {
        observers.push({ cb, els: this.els });
      }
      observe(el: Element) {
        this.els.push(el);
      }
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    try {
      renderWithClient(
        <DataTable
          caption="Matrix"
          rows={rows}
          rowKey={(r) => r.id}
          columns={[
            { key: "no", header: "Case", cell: (r) => r.no, primary: true },
            { key: "stage", header: "Stage", cell: (r) => r.stage },
          ]}
        />,
      );
      const table = screen.getByRole("table", { name: "Matrix" });
      const wrap = table.parentElement!;
      expect(wrap).not.toHaveAttribute("data-stacked");
      const watcher = observers.find((o) => o.els.includes(wrap));
      expect(watcher).toBeDefined();
      Object.defineProperty(wrap, "clientWidth", { configurable: true, value: 722 });
      Object.defineProperty(table, "offsetWidth", { configurable: true, value: 1629 });
      act(() => watcher!.cb([], watcher as unknown as ResizeObserver));
      expect(wrap).toHaveAttribute("data-stacked");
      Object.defineProperty(wrap, "clientWidth", { configurable: true, value: 1700 });
      act(() => watcher!.cb([], watcher as unknown as ResizeObserver));
      expect(wrap).not.toHaveAttribute("data-stacked");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("shows the empty state instead of an empty table", () => {
    renderWithClient(
      <DataTable rows={[]} rowKey={() => "x"} columns={[]} empty={<EmptyState title="Nothing waiting">New files appear here.</EmptyState>} />,
    );
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
    expect(screen.getByText("New files appear here.")).toBeInTheDocument();
  });
});

describe("the alignment rule (decision 15)", () => {
  it("Lead, DateChip and LeadIcon put the leading element in its fixed column inside ListRow", () => {
    const { container } = renderWithClient(
      <ul>
        <ListRow
          as="li"
          lead={
            <Lead>
              <Badge tone="danger">Overdue 6 days</Badge>
            </Lead>
          }
        >
          <strong>Reply to be filed</strong>
        </ListRow>
        <ListRow as="li" lead={<DateChip date="2026-10-22" hot />}>
          WP(C)/1234/2026
        </ListRow>
        <ListRow as="li" lead={<LeadIcon>•</LeadIcon>} trail={<span>›</span>}>
          A note was added
        </ListRow>
      </ul>,
    );
    const items = container.querySelectorAll("li");
    expect(items[0]!.firstElementChild).toHaveAttribute("data-lead", "lead");
    expect(within(items[0]!.firstElementChild as HTMLElement).getByText("Overdue 6 days")).toBeInTheDocument();
    expect(items[1]!.firstElementChild).toHaveAttribute("data-lead", "date");
    expect(within(items[1]!).getByText("22")).toBeInTheDocument();
    expect(within(items[1]!).getByText("Oct")).toBeInTheDocument();
    expect(items[1]!.querySelector("time")).toHaveAttribute("title", "22 Oct 2026");
    expect(items[2]!.firstElementChild).toHaveAttribute("data-lead", "icon");
  });

  it("a long badge keeps its full text as its title and accessible text", () => {
    renderWithClient(
      <Lead>
        <Badge tone="warning">Next date from order · confirm</Badge>
      </Lead>,
    );
    expect(screen.getByTitle("Next date from order · confirm")).toHaveTextContent("Next date from order · confirm");
  });
});

describe("badges and feedback", () => {
  it('ScoreBadge shows "Strong · 0.950" from band high, whatever the number', () => {
    renderWithClient(
      <>
        <ScoreBadge score={0.95} band="high" />
        <ScoreBadge score={0.62} band="medium" />
        <ScoreBadge score={0.4} band="high" />
      </>,
    );
    expect(screen.getByText("Strong · 0.950")).toBeInTheDocument();
    expect(screen.getByText("Possible · 0.620")).toBeInTheDocument();
    expect(screen.getByText("Strong · 0.400")).toBeInTheDocument();
  });

  it("Loading shows skeleton rows and keeps the visually hidden status text", () => {
    renderWithClient(<Loading />);
    const status = screen.getByRole("status");
    expect(within(status).getByText("Loading…")).toHaveClass("visually-hidden");
  });

  it("the Stepper names the step", () => {
    renderWithClient(<Stepper step={2} steps={["Who Receives It", "What They Should Do", "Remark and Confirm"]} />);
    expect(screen.getByText("Step 2 of 3 · What They Should Do")).toBeInTheDocument();
  });

  it("the Meter carries its value", () => {
    renderWithClient(<Meter value={0.62} label="Match Strength" />);
    expect(screen.getByRole("meter", { name: "Match Strength" })).toHaveAttribute("aria-valuenow", "0.62");
  });
});

describe("chips, switches and the page header", () => {
  it("a Chip toggles aria-pressed and a FilterChip names what it removes", async () => {
    const remove = vi.fn();
    function Harness() {
      const [on, setOn] = useState(false);
      return (
        <>
          <Chip on={on} onClick={() => setOn((v) => !v)}>
            Hearing this week
          </Chip>
          <FilterChip label="Officer: Not allotted" onRemove={remove} />
        </>
      );
    }
    renderWithClient(<Harness />);
    const chip = screen.getByRole("button", { name: "Hearing this week" });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Remove filter: Officer: Not allotted" }));
    expect(remove).toHaveBeenCalled();
  });

  it("the SegmentedSwitch is a radiogroup moved by the arrow keys", async () => {
    function Harness() {
      const [v, setV] = useState("mine");
      return (
        <SegmentedSwitch
          label="View"
          value={v}
          onChange={setV}
          options={[
            { value: "mine", label: "My Dates" },
            { value: "department", label: "Department Hearings" },
          ]}
        />
      );
    }
    renderWithClient(<Harness />);
    const group = screen.getByRole("radiogroup", { name: "View" });
    const mine = within(group).getByRole("radio", { name: "My Dates" });
    expect(mine).toHaveAttribute("aria-checked", "true");
    mine.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(within(group).getByRole("radio", { name: "Department Hearings" })).toHaveAttribute("aria-checked", "true");
    expect(within(group).getByRole("radio", { name: "Department Hearings" })).toHaveFocus();
  });

  it("the PageHeader holds one primary action and secondary actions", () => {
    resetNav("/files");
    renderWithClient(
      <PageHeader
        title="Files"
        subtitle="Files sent to you"
        primary={<Button>Send file</Button>}
        actions={<Button variant="secondary">Print</Button>}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Files" })).toBeInTheDocument();
    expect(screen.getByText("Files sent to you")).toBeInTheDocument();
    expect(document.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
  });
});

describe("password fields", () => {
  it("every password field has a show / hide toggle that switches the input type and its own label", async () => {
    const user = userEvent.setup();
    renderWithClient(<TextField label="Password" type="password" defaultValue="s3cret" />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    const toggle = screen.getByRole("button", { name: "Show Password" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toHaveAttribute("type", "button");
    await user.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide Password" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Hide Password" }));
    expect(input).toHaveAttribute("type", "password");
  });

  it("other fields carry no toggle", () => {
    renderWithClient(<TextField label="E-mail" type="email" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("CheckField inline (design portal-ui-polish-2, decision 26)", () => {
  it("marks a checkbox that sits on a field row's control line, and only when asked", () => {
    renderWithClient(
      <>
        <CheckField label="Include Sub-offices" inline />
        <CheckField label="Show Archived" />
      </>,
    );
    const inline = screen.getByLabelText("Include Sub-offices").parentElement!;
    const plain = screen.getByLabelText("Show Archived").parentElement!;
    expect(inline).toHaveAttribute("data-inline", "true");
    expect(inline.className).toMatch(/checkInline/);
    expect(plain).not.toHaveAttribute("data-inline");
    expect(plain.className).not.toMatch(/checkInline/);
  });
});

describe("FilterCard (design portal-ui-polish-2, decision 21)", () => {
  function Card({ moreCount = 0, onSubmit = vi.fn() }: { moreCount?: number; onSubmit?: () => void }) {
    return (
      <FilterCard
        label="Case Filters"
        hero={<TextField label="Search For" />}
        onSubmit={onSubmit}
        more={<TextField label="Year" />}
        moreCount={moreCount}
        summary={<span>12 cases match</span>}
      >
        <TextField label="Case Type" />
        <TextField label="Department" />
      </FilterCard>
    );
  }

  it("draws the hero zone, then the fields grid with the actions in its last cell", () => {
    const { container } = renderWithClient(<Card />);
    const form = screen.getByRole("search", { name: "Case Filters" });
    const hero = container.querySelector("[data-zone='hero']")!;
    const fields = container.querySelector("[data-zone='fields']")!;
    expect(within(hero as HTMLElement).getByLabelText("Search For")).toBeInTheDocument();
    expect(within(fields as HTMLElement).getByLabelText("Case Type")).toBeInTheDocument();
    expect(within(fields as HTMLElement).getByLabelText("Department")).toBeInTheDocument();
    // the stacked order on phones is the DOM order: hero, fields, actions (the zones carry their classes)
    expect([...form.children].map((c) => c.getAttribute("data-zone"))).toEqual(["hero", "fields"]);
    expect(hero.className).toMatch(/fcHero/);
    expect(fields.className).toMatch(/fcRight/);
    const grid = fields.firstElementChild!;
    expect(grid.className).toMatch(/fcGrid/);
    const actions = grid.lastElementChild!;
    expect(actions.getAttribute("data-zone")).toBe("actions");
    expect(within(actions as HTMLElement).getByRole("button", { name: "Search" })).toHaveAttribute("type", "submit");
    expect(within(actions as HTMLElement).getByRole("button", { name: "More Filters" })).toBeInTheDocument();
  });

  it("Search submits the form, Enter in a field too", async () => {
    const onSubmit = vi.fn();
    renderWithClient(<Card onSubmit={onSubmit} />);
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    await userEvent.type(screen.getByLabelText("Case Type"), "WP(C){Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });

  it("More Filters opens the panel inside the card and mounts its fields on first opening", async () => {
    renderWithClient(<Card />);
    const button = screen.getByRole("button", { name: "More Filters" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("Year")).toBeNull();
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const panel = document.getElementById(button.getAttribute("aria-controls")!)!;
    expect(panel).toHaveAttribute("data-zone", "more");
    expect(within(panel).getByLabelText("Year")).toBeInTheDocument();
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(panel).toHaveAttribute("aria-hidden", "true");
  });

  it("shows the number of set fields inside and is open while one is set", () => {
    renderWithClient(<Card moreCount={2} />);
    const button = screen.getByRole("button", { name: "More Filters (2)" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Year")).toBeInTheDocument();
  });

  it("draws the summary strip under the card, and no More Filters without fields for it", () => {
    const { container } = renderWithClient(
      <FilterCard label="Queue Filters" hero={<TextField label="Reference Starts With" />} summary={<span>3 rows</span>}>
        <TextField label="Kind" />
      </FilterCard>,
    );
    const strip = container.querySelector("[data-zone='summary']")!;
    expect(strip).toHaveTextContent("3 rows");
    expect(strip.className).toMatch(/fcStrip/);
    expect(screen.queryByRole("button", { name: /More Filters/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Search" })).toBeNull();
    expect(screen.getByRole("group", { name: "Queue Filters" })).toBeInTheDocument();
  });

  it("keeps the hero mounted when a submit arrives with the page's data", async () => {
    function Harness() {
      const [loaded, setLoaded] = useState(false);
      return (
        <FilterCard
          label="Filters"
          hero={
            <button type="button" onClick={() => setLoaded(true)}>
              Hero
            </button>
          }
          onSubmit={loaded ? () => undefined : undefined}
        >
          {loaded ? <TextField label="Bench" /> : null}
        </FilterCard>
      );
    }
    renderWithClient(<Harness />);
    const before = screen.getByRole("button", { name: "Hero" });
    await userEvent.click(before);
    expect(screen.getByLabelText("Bench")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hero" })).toBe(before);
  });
});

describe("progress, scroll box and captions (design data-collection-redesign, decisions 9-11)", () => {
  it("ProgressBar is a progressbar with the done amount, the whole and a sentence, shown as text too", () => {
    renderWithClient(
      <ProgressBar
        label="Order PDFs"
        max={10}
        segments={[
          { tone: "failed", value: 1 },
          { tone: "done", value: 6 },
          { tone: "waiting", value: 2 },
          { tone: "unavailable", value: 1 },
        ]}
        text="6 of 10 stored, 2 waiting"
      />,
    );
    const bar = screen.getByRole("progressbar", { name: "Order PDFs" });
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "10");
    expect(bar).toHaveAttribute("aria-valuenow", "6");
    expect(bar).toHaveAttribute("aria-valuetext", "6 of 10 stored, 2 waiting");
    expect(screen.getByText("6 of 10 stored, 2 waiting")).toBeInTheDocument();
    // segments in a fixed order, sized as shares of the whole, never colour alone
    const segs = [...bar.querySelectorAll<HTMLElement>("[data-tone]")];
    expect(segs.map((s) => s.dataset.tone)).toEqual(["done", "waiting", "unavailable", "failed"]);
    expect(parseFloat(segs[0]!.style.width)).toBe(60);
  });

  it("ProgressBar can leave its sentence to the caller, and draws nothing for an empty whole", () => {
    renderWithClient(<ProgressBar label="Days" max={0} segments={[{ tone: "done", value: 0 }]} text="No days" showText={false} />);
    const bar = screen.getByRole("progressbar", { name: "Days" });
    expect(bar).toHaveAttribute("aria-valuetext", "No days");
    expect(bar.querySelectorAll("[data-tone]")).toHaveLength(0);
    expect(screen.queryByText("No days", { selector: "span" })).toBeNull();
  });

  it("ProgressLegend names each tone in words", () => {
    renderWithClient(
      <ProgressLegend
        items={[
          { tone: "done", label: "Stored", value: "6" },
          { tone: "failed", label: "Failed" },
        ]}
      />,
    );
    const legend = screen.getByRole("list", { name: "Legend" });
    expect(within(legend).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Stored6", "Failed"]);
  });

  it("the motion tokens go to 0 ms under reduced motion, so the bars do not grow and nothing pulses", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const css = readFileSync(join(process.cwd(), "src", "components", "ui", "feedback.module.css"), "utf-8");
    expect(css).toMatch(/\.progressSeg \{[^}]*animation: progress-grow var\(--slow\)/);
    expect(css).toMatch(/progress-pulse calc\(var\(--slow\) \* 5\)/);
    const globals = readFileSync(join(process.cwd(), "src", "app", "globals.css"), "utf-8");
    expect(globals).toMatch(/prefers-reduced-motion: reduce[\s\S]*--slow: 0ms/);
  });

  it("ScrollBox is a named, focusable region", () => {
    renderWithClient(
      <ScrollBox label="Month by Month">
        <p>rows</p>
      </ScrollBox>,
    );
    const box = screen.getByRole("region", { name: "Month by Month" });
    expect(box).toHaveAttribute("tabindex", "0");
    expect(box).toHaveAttribute("data-scroll-y");
  });

  it("DataTable hides its caption unless showCaption, keeping it as the accessible name", () => {
    const columns = [{ key: "a", header: "A", primary: true, cell: (r: { id: string }) => r.id }];
    const { unmount } = renderWithClient(<DataTable caption="Hidden Name" rows={[{ id: "x" }]} rowKey={(r) => r.id} columns={columns} />);
    expect(screen.getByRole("table", { name: "Hidden Name" }).querySelector("caption")!.className).toMatch(/srCaption/);
    unmount();
    renderWithClient(<DataTable caption="Shown Name" showCaption rows={[{ id: "x" }]} rowKey={(r) => r.id} columns={columns} />);
    expect(screen.getByRole("table", { name: "Shown Name" }).querySelector("caption")!.className).toBe("");
  });

  it("TabToolbar says when the figures were updated, with its links on the right", () => {
    const { container } = renderWithClient(
      <TabToolbar updatedAt={Date.now() - 12_000}>
        <a href="/reports/data-health">Report</a>
      </TabToolbar>,
    );
    const bar = container.querySelector("[data-ui='tab-toolbar']")!;
    expect(bar).toHaveTextContent("Updated 12 s ago");
    expect(within(bar as HTMLElement).getByRole("link", { name: "Report" })).toBeInTheDocument();
  });
});

describe("ProgressBar never holds more than the whole", () => {
  it("clamps segments that add up past the whole", () => {
    renderWithClient(
      <ProgressBar
        label="Over"
        max={10}
        segments={[
          { tone: "done", value: 8 },
          { tone: "waiting", value: 8 },
        ]}
        text="8 of 10"
      />,
    );
    const segs = [...screen.getByRole("progressbar", { name: "Over" }).querySelectorAll<HTMLElement>("[data-tone]")];
    expect(segs.map((s) => parseFloat(s.style.width))).toEqual([80, 20]);
  });
});
