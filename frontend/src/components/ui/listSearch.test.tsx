/** The kit's list search (design list-search, decisions 2, 4, 7 and 8). */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { searchShown } from "@/lib/listSearch";
import { useListState } from "@/lib/useListState";
import { resetNav } from "@/test/nav";

import { ListCount, ListSearch, ListToolbar, NoMatches } from "./listSearch";

/** A list that shows what it would send: the typed search and the applied one. */
function ServerList({ rows = 20 }: { rows?: number }) {
  const state = useListState({ mode: "local", search: "server" });
  return (
    <>
      <ListToolbar
        search={
          searchShown(rows, state.q) ? (
            <ListSearch label="Search Codes" placeholder="Code or part of a code" value={state.q} onChange={state.setQ} onEnter={state.apply} minChars={2} />
          ) : null
        }
      />
      <output data-testid="applied">{state.applied}</output>
    </>
  );
}

beforeEach(() => resetNav("/admin/mapping/codes"));

describe("the debounce (decision 4)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("waits 300 ms after the last keystroke, and Enter sends at once", () => {
    render(<ServerList />);
    const box = screen.getByRole("searchbox", { name: "Search Codes" });
    fireEvent.change(box, { target: { value: "ga" } });
    expect(screen.getByTestId("applied")).toBeEmptyDOMElement();
    act(() => vi.advanceTimersByTime(299));
    expect(screen.getByTestId("applied")).toBeEmptyDOMElement();
    act(() => vi.advanceTimersByTime(2));
    expect(screen.getByTestId("applied")).toHaveTextContent("ga");
    fireEvent.change(box, { target: { value: "ga assam" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(screen.getByTestId("applied")).toHaveTextContent("ga assam");
  });

  it("never applies a search shorter than two letters, and says so in the tooltip", () => {
    render(<ServerList />);
    const box = screen.getByRole("searchbox", { name: "Search Codes" });
    expect(box).toHaveAttribute("title", "Type at least 2 letters.");
    fireEvent.change(box, { target: { value: "g" } });
    fireEvent.keyDown(box, { key: "Enter" });
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByTestId("applied")).toBeEmptyDOMElement();
  });
});

describe("ListSearch", () => {
  it("is a search field in a named search region with a hidden label shown as the placeholder", () => {
    render(<ListSearch label="Search Tickets" placeholder="Reference or department" value="" onChange={() => {}} />);
    expect(screen.getByRole("search", { name: "Search Tickets" })).toBeInTheDocument();
    const box = screen.getByRole("searchbox", { name: "Search Tickets" });
    expect(box).toHaveAttribute("type", "search");
    expect(box).toHaveAttribute("placeholder", "Reference or department");
    expect(screen.queryByRole("button", { name: "Clear Search" })).toBeNull();
  });

  it("Clear Search and Escape clear the field and return focus to it", async () => {
    render(<ServerList />);
    const box = screen.getByRole("searchbox", { name: "Search Codes" });
    await userEvent.type(box, "ram");
    await userEvent.click(screen.getByRole("button", { name: "Clear Search" }));
    expect(box).toHaveValue("");
    expect(box).toHaveFocus();
    await userEvent.type(box, "ram");
    await userEvent.keyboard("{Escape}");
    expect(box).toHaveValue("");
    expect(box).toHaveFocus();
  });

  it("shows a small spinner while a server search runs", () => {
    const { container } = render(<ListSearch label="Search Codes" value="ga" onChange={() => {}} busy />);
    expect(container.querySelector('[data-ui="list-search-busy"]')).not.toBeNull();
  });

  it("hides the browser's own cancel button so every browser shows the same control", () => {
    const css = readFileSync(join(process.cwd(), "src", "components", "ui", "listSearch.module.css"), "utf-8");
    expect(css).toMatch(/::-webkit-search-cancel-button[^{]*\{[^}]*appearance:\s*none/);
  });
});

describe("the count (decision 7)", () => {
  it("reads 340 codes, 12 of 340 codes or 12 codes match", () => {
    const { rerender } = render(<ListCount shown={340} noun="codes" searching={false} />);
    expect(screen.getByText("340 codes")).toHaveAttribute("aria-live", "polite");
    rerender(<ListCount shown={12} total={340} noun="codes" searching />);
    expect(screen.getByText("12 of 340 codes")).toBeInTheDocument();
    rerender(<ListCount shown={12} noun="codes" searching />);
    expect(screen.getByText("12 codes match")).toBeInTheDocument();
    rerender(<ListCount shown={1066} noun="codes" allNoun="codes not mapped" searching={false} />);
    expect(screen.getByText("1,066 codes not mapped")).toBeInTheDocument();
  });
});

describe("NoMatches (decision 8)", () => {
  it("shows the query and a Clear Search button", async () => {
    const onClear = vi.fn();
    render(<NoMatches q=" ram " onClear={onClear} />);
    expect(screen.getByText("No matches for “ram”.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Clear Search" }));
    expect(onClear).toHaveBeenCalledOnce();
  });
});

describe("when the box shows (decision 8)", () => {
  it("is hidden at 10 rows and shown at 11 or with a search set", () => {
    const { rerender } = render(<ServerList rows={10} />);
    expect(screen.queryByRole("searchbox")).toBeNull();
    rerender(<ServerList rows={11} />);
    expect(screen.getByRole("searchbox", { name: "Search Codes" })).toBeInTheDocument();
  });
});
