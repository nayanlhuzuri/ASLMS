import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LinkGraph } from "@/components/case/LinkGraph";
import type { LinkGraph as LinkGraphOut } from "@/lib/api/types";
import { renderWithClient } from "@/test/render";

import { alertTone, Kpi, Notice, ScoreBadge, SeverityBadge } from "./index";

/* The kit pieces of the navy-and-cream row (design portal-navy-cream): the one headline tile, the notice tones, one
   recommendation tone on every screen and the alert tone by meaning. The colours themselves are pinned in
   tokens.test.ts and the layout in layoutSignature.test.ts. */

describe("Kpi emphasis (decision 10)", () => {
  it("carries .kpiMark only with emphasis, as a link or as a plain tile", () => {
    renderWithClient(
      <>
        <Kpi label="Marked" value={3} href="/inbox/with-me" emphasis />
        <Kpi label="Plain" value={3} href="/calendar" />
        <Kpi label="Marked Tile" value={1} emphasis />
        <Kpi label="Plain Tile" value={1} />
      </>,
    );
    expect(screen.getByRole("link", { name: "Marked: 3" }).className).toMatch(/kpiMark/);
    expect(screen.getByRole("link", { name: "Plain: 3" }).className).not.toMatch(/kpiMark/);
    expect(screen.getByText("Marked Tile").parentElement!.className).toMatch(/kpiMark/);
    expect(screen.getByText("Plain Tile").parentElement!.className).not.toMatch(/kpiMark/);
  });
});

describe("Notice tones (addendum K7)", () => {
  it("is the neutral info tone by default; success and warning only when chosen", () => {
    render(
      <>
        <Notice>Information</Notice>
        <Notice tone="success">Saved</Notice>
        <Notice tone="warning">Switched off</Notice>
      </>,
    );
    expect(screen.getByText("Information")).toHaveAttribute("data-tone", "info");
    expect(screen.getByText("Saved")).toHaveAttribute("data-tone", "success");
    expect(screen.getByText("Switched off")).toHaveAttribute("data-tone", "warning");
  });
});

describe("one recommendation tone on every screen (addendum C4)", () => {
  it("a strong match is solid navy, a possible one outlined navy, anything else neutral", () => {
    render(
      <>
        <ScoreBadge score={0.95} band="high" />
        <ScoreBadge score={0.62} band="medium" />
        <ScoreBadge score={0.3} band="low" />
      </>,
    );
    const strong = screen.getByTitle("Strong · 0.950");
    expect(strong.className).toMatch(/badge-info/);
    expect(strong).toHaveAttribute("data-look", "solid");
    const possible = screen.getByTitle("Possible · 0.620");
    expect(possible.className).toMatch(/badge-info/);
    expect(possible).toHaveAttribute("data-look", "outline");
    const other = screen.getByTitle("Low · 0.300");
    expect(other.className).not.toMatch(/badge-info/);
    expect(other).not.toHaveAttribute("data-look");
  });
});

describe("the alert tone by meaning, never by severity (addendum A1)", () => {
  // Wednesday 11 Nov 2026, 12:00 IST
  const NOW = new Date("2026-11-11T06:30:00Z");

  it("a hearing alert takes its hearing date's band", () => {
    expect(alertTone("listed_tomorrow", { hearing_date: "2026-11-12" }, NOW)).toEqual({ tone: "danger" });
    expect(alertTone("hearing_due", { hearing_date: "2026-11-11" }, NOW)).toEqual({ tone: "danger" });
    expect(alertTone("hearing_due", { hearing_date: "2026-11-15" }, NOW)).toEqual({ tone: "warning" });
    expect(alertTone("hearing_due", { hearing_date: "2026-12-20" }, NOW)).toEqual({});
    expect(alertTone("hearing_due", { hearing_date: "2026-11-01" }, NOW)).toEqual({});
    expect(alertTone("hearing_due", {}, NOW)).toEqual({});
  });

  it("a recommendation is navy, solid when strong and outlined when possible; the rest is neutral", () => {
    expect(alertTone("recommendation", { band: "high" })).toEqual({ tone: "info", look: "solid" });
    expect(alertTone("recommendation", { band: "medium" })).toEqual({ tone: "info", look: "outline" });
    expect(alertTone("recommendation", {})).toEqual({});
    expect(alertTone("note_added", { hearing_date: "2026-11-12" }, NOW)).toEqual({});
    expect(alertTone(undefined, undefined)).toEqual({});
  });

  it("a critical alert that is not about a hearing is no longer red", () => {
    render(<SeverityBadge severity="critical" kind="transfer_requested" data={{}} />);
    const badge = screen.getByText("Critical").parentElement!;
    expect(badge.className).not.toMatch(/badge-danger/);
  });

  it("keeps the severity in words", () => {
    render(<SeverityBadge severity="normal" kind="recommendation" data={{ band: "high" }} />);
    const badge = screen.getByText("Normal").parentElement!;
    expect(badge.className).toMatch(/badge-info/);
    expect(badge).toHaveAttribute("data-look", "solid");
  });
});

describe("LinkGraph colours from classes (decision 7)", () => {
  const graph = {
    nodes: [
      { key: "a", visible: true, case_no_text: "WP(C)/1/2026", case: { id: "c1", ref_no: "ASLMS/GHC/CASE/2026/000001", case_no_text: "WP(C)/1/2026" } },
      { key: "b", visible: true, case_no_text: "WA/2/2026", case: { id: "c2", ref_no: "ASLMS/GHC/CASE/2026/000002", case_no_text: "WA/2/2026" } },
      { key: "c", visible: false, case_no_text: "WA/3/2026", case: null },
    ],
    edges: [
      { from: "a", to: "b", kind: "appeal" },
      { from: "a", to: "c", kind: "connected" },
    ],
    truncated: false,
  } as unknown as LinkGraphOut;

  it("renders no fill or stroke attribute holding a colour, and every node carries its class", () => {
    const { container } = renderWithClient(<LinkGraph graph={graph} rootId="c1" />);
    for (const el of container.querySelectorAll("svg *")) {
      for (const attr of ["fill", "stroke"]) {
        const value = el.getAttribute(attr);
        if (value !== null) expect(value, `${el.tagName} ${attr}`).toMatch(/^(none|currentColor)$/);
      }
    }
    const rect = (key: string) => container.querySelector(`[data-node="${key}"] rect`)!;
    expect(rect("a").getAttribute("class")).toMatch(/graphRoot/);
    expect(rect("b").getAttribute("class")).toMatch(/graphNode/);
    expect(rect("c").getAttribute("class")).toMatch(/graphHidden/);
    expect(container.querySelector('[data-node="a"] text')!.getAttribute("class")).toMatch(/graphRootText/);
    expect(container.querySelector('[data-node="c"] text')!.getAttribute("class")).toMatch(/graphHiddenText/);
    for (const line of container.querySelectorAll("line")) expect(line.getAttribute("class")).toMatch(/graphEdge/);
  });
});
