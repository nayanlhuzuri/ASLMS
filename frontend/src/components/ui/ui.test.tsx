import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetNav } from "@/test/nav";
import { renderWithClient } from "@/test/render";

import {
  Badge,
  Button,
  Chip,
  Collapsible,
  controlClass,
  DataTable,
  DateChip,
  Dialog,
  EmptyState,
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
        label="Case sections"
        items={[
          { href: "/a", label: "Overview", active: false },
          { href: "/b", label: "Orders", active: true, count: 4 },
        ]}
      />,
    );
    const nav = screen.getByRole("navigation", { name: "Case sections" });
    expect(within(nav).getByRole("link", { name: "Orders (4)" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(screen.getByTestId("tab-ink")).toBeInTheDocument();
  });

  it("puts the more group in a menu whose button names the current tab", async () => {
    renderWithClient(
      <Tabs
        label="Case sections"
        items={[{ href: "/a", label: "Overview", active: false }]}
        more={[
          { href: "/p", label: "Parties", active: true },
          { href: "/l", label: "Linked cases", active: false },
        ]}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Parties" });
    await userEvent.click(trigger);
    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "Parties" })).toHaveAttribute("aria-current", "page");
    expect(within(menu).getByRole("menuitem", { name: "Linked cases" })).toHaveAttribute("href", "/l");
  });

  it("the more button reads More when none of its tabs is current", () => {
    renderWithClient(
      <Tabs label="Case sections" items={[{ href: "/a", label: "Overview", active: true }]} more={[{ href: "/p", label: "Parties", active: false }]} />,
    );
    expect(screen.getByRole("button", { name: "More" })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("Menu", () => {
  it("opens and closes by keyboard, with arrow keys between the items", async () => {
    const onSelect = vi.fn();
    renderWithClient(
      <Menu
        label="More actions"
        items={[
          { key: "recall", label: "Recall", onSelect },
          { key: "stage", label: "Set stage" },
        ]}
      />,
    );
    const button = screen.getByRole("button", { name: "More actions" });
    button.focus();
    await userEvent.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitem", { name: "Recall" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Set stage" })).toHaveFocus();
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

describe("Collapsible", () => {
  it("toggles aria-expanded and mounts its body on first opening", async () => {
    renderWithClient(
      <Collapsible summary="Show parties, advocates and acts">
        <p>Petitioner A</p>
      </Collapsible>,
    );
    const button = screen.getByRole("button", { name: "Show parties, advocates and acts" });
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
    renderWithClient(<Stepper step={2} steps={["Who receives it", "What they should do", "Remark and confirm"]} />);
    expect(screen.getByText("Step 2 of 3 · What they should do")).toBeInTheDocument();
  });

  it("the Meter carries its value", () => {
    renderWithClient(<Meter value={0.62} label="Match strength" />);
    expect(screen.getByRole("meter", { name: "Match strength" })).toHaveAttribute("aria-valuenow", "0.62");
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
            { value: "mine", label: "My dates" },
            { value: "department", label: "Department hearings" },
          ]}
        />
      );
    }
    renderWithClient(<Harness />);
    const group = screen.getByRole("radiogroup", { name: "View" });
    const mine = within(group).getByRole("radio", { name: "My dates" });
    expect(mine).toHaveAttribute("aria-checked", "true");
    mine.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(within(group).getByRole("radio", { name: "Department hearings" })).toHaveAttribute("aria-checked", "true");
    expect(within(group).getByRole("radio", { name: "Department hearings" })).toHaveFocus();
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
