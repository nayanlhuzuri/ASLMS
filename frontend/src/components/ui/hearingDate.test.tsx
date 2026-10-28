/**
 * The kit's next hearing badge (design next-hearing-highlight, decisions 1 and 4-9).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HearingDate } from "./index";

// 12:00 IST on Tuesday 27 Oct 2026
const NOW = new Date("2026-10-27T06:30:00Z");

function badge(container: HTMLElement): HTMLElement {
  return container.querySelector("[data-band]") as HTMLElement;
}

describe("HearingDate", () => {
  it.each([
    ["2026-10-27", "today", "Today · 27 Oct 2026"],
    ["2026-10-28", "tomorrow", "Tomorrow · 28 Oct 2026"],
    ["2026-10-30", "week", "In 3 Days · 30 Oct 2026"],
    ["2026-11-16", "later", "16 Nov 2026"],
    ["2026-10-22", "passed", "Date Passed · 22 Oct 2026"],
  ])("%s renders the %s band with its words and the date", (date, band, text) => {
    const { container } = render(<HearingDate date={date} now={NOW} />);
    const el = badge(container);
    expect(el).toHaveAttribute("data-band", band);
    expect(el).toHaveAttribute("data-kind", "firm");
    expect(el).toHaveTextContent(text);
    expect(el.querySelector("time")).toHaveAttribute("dateTime", date);
  });

  it("reads No Date Yet without a date and Disposed for a disposed case, with no time", () => {
    const none = render(<HearingDate date={null} now={NOW} />);
    expect(badge(none.container)).toHaveAttribute("data-band", "none");
    expect(badge(none.container)).toHaveTextContent(/^No Date Yet$/);
    expect(badge(none.container).querySelector("time")).toBeNull();
    const disposed = render(<HearingDate date="2026-10-28" status="disposed" now={NOW} />);
    expect(badge(disposed.container)).toHaveAttribute("data-band", "disposed");
    expect(badge(disposed.container)).toHaveTextContent(/^Disposed$/);
    expect(badge(disposed.container).querySelector("time")).toBeNull();
  });

  it("shows the weekday and the countdown of a later date in the medium size", () => {
    const { container } = render(<HearingDate date="2026-11-16" size="md" now={NOW} />);
    expect(badge(container)).toHaveTextContent("In 20 Days · Mon, 16 Nov 2026");
  });

  it("gives the word alone with showDate off, even for a later date", () => {
    const { container, rerender } = render(<HearingDate date="2026-10-28" showDate={false} now={NOW} />);
    expect(badge(container)).toHaveTextContent(/^Tomorrow$/);
    expect(badge(container).querySelector("time")).toBeNull();
    rerender(<HearingDate date="2026-11-16" showDate={false} now={NOW} />);
    expect(badge(container)).toHaveTextContent(/^In 20 Days$/);
  });

  it("outlines a suggested date with Suggested first and its sentence", () => {
    const { container } = render(<HearingDate date="2026-10-30" kind="suggested" size="md" now={NOW} />);
    const el = badge(container);
    expect(el).toHaveAttribute("data-kind", "suggested");
    expect(el).toHaveTextContent("Suggested · In 3 Days · Fri, 30 Oct 2026");
    expect(el).toHaveAttribute("title", "Read from an order and not yet confirmed.");
  });

  it("explains a passed date in its title and draws the icon hidden from screen readers", () => {
    const { container } = render(<HearingDate date="2026-10-22" now={NOW} />);
    const el = badge(container);
    expect(el).toHaveAttribute("title", "The court's next date has passed and no newer date is held yet.");
    expect(el.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("lets the visible words be what a screen reader reads", () => {
    const { container } = render(<HearingDate date="2026-10-28" size="md" now={NOW} />);
    const el = badge(container);
    expect(container.querySelector("[aria-label]")).toBeNull();
    expect(el.querySelector('[aria-hidden="true"]')).toHaveTextContent("·");
    // the readable words: everything but the hidden separator
    const clone = el.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
    expect(clone.querySelector("span")).toHaveTextContent(/^Tomorrow$/);
    expect(clone.querySelector("time")).toHaveTextContent(/^Wed, 28 Oct 2026$/);
  });

  it("hides every separator from screen readers, the one after Suggested too (review advisory 2)", () => {
    for (const size of ["sm", "md"] as const) {
      const { container, unmount } = render(<HearingDate date="2026-10-30" kind="suggested" size={size} now={NOW} />);
      const el = badge(container);
      expect(el).toHaveTextContent(/^Suggested · In 3 Days · /);
      expect(el.querySelectorAll('[aria-hidden="true"]')).toHaveLength(2);
      const clone = el.cloneNode(true) as HTMLElement;
      clone.querySelectorAll('[aria-hidden="true"]').forEach((n) => n.remove());
      expect(clone.textContent).not.toContain("·");
      expect(clone.textContent).toContain("Suggested");
      expect(clone.textContent).toContain("In 3 Days");
      unmount();
    }
    // a later suggested date in a list: "Suggested" alone, no stray separator
    const { container } = render(<HearingDate date="2026-11-16" kind="suggested" now={NOW} />);
    expect(badge(container).firstElementChild).toHaveTextContent(/^Suggested$/);
  });

  it("lets the medium badge wrap between words in a narrow column, never cutting it (review advisory 1)", () => {
    const css = readFileSync(join(process.cwd(), "src/components/ui/hearingDate.module.css"), "utf-8");
    const root = css.match(/\.root\s*\{([^}]*)\}/)![1]!;
    expect(root).toMatch(/min-width:\s*0/);
    expect(root).toMatch(/max-width:\s*100%/);
    const md = css.match(/\.md \.word,\s*\.md \.date\s*\{([^}]*)\}/)![1]!;
    expect(md).toMatch(/white-space:\s*normal/);
    expect(md).toMatch(/overflow-wrap:\s*anywhere/);
    expect(md).toMatch(/min-width:\s*0/);
    expect(md).not.toMatch(/overflow:|text-overflow/);
    const frame = readFileSync(join(process.cwd(), "src/components/case/case.module.css"), "utf-8");
    expect(frame.match(/\.factLine\s*\{([^}]*)\}/)![1]).toMatch(/max-width:\s*100%/);
  });

  it("never uses the kit Badge's truncating text", () => {
    const tsx = readFileSync(join(process.cwd(), "src/components/ui/HearingDate.tsx"), "utf-8");
    const css = readFileSync(join(process.cwd(), "src/components/ui/hearingDate.module.css"), "utf-8");
    expect(tsx).not.toMatch(/badgeText|feedback\.module\.css|<Badge/);
    expect(css).not.toMatch(/text-overflow|overflow:\s*hidden/);
    expect(css).toMatch(/white-space:\s*nowrap/);
    expect(css).toMatch(/flex-wrap:\s*wrap/);
  });
});
