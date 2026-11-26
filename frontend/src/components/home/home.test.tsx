/**
 * The public home page (design home-page, row 274, decisions 4, 5, 7 and 10; design home-page-refinements, row 281,
 * decisions 1 to 4): it holds the sign-in form as its only sign-in, has no top bar and no closing band, has one primary
 * action, shows the emblem and the frame's names in its hero with a link to the samples at its foot, two plainly sample
 * and inert pictures of the real screens, the four-item strip, and no real identifier, department or court name.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { T } from "@/lib/messages";
import { resetNav } from "@/test/nav";
import { primaryActions, renderWithClient } from "@/test/render";

import { HomePage } from "./HomePage";
import { SAMPLE_ROWS } from "./sampleData";

const E2E = join(process.cwd(), "e2e", "fixtures");

/**
 * The department and office names of the browser check's fixtures (`e2e/fixtures`), read statically: the office list's
 * `item("CODE", "Name", …)` entries, every `{ code: "…", name: "…" }` department, and the long office name of the
 * stress values. "Government of Assam", the State tier, is the owner's name that the page shows on purpose.
 */
function fixtureOfficeNames(): string[] {
  const text = ["index.ts", "insights.ts"].map((f) => readFileSync(join(E2E, f), "utf-8")).join("\n");
  const names = new Set<string>();
  for (const m of text.matchAll(/item\("[A-Z-]+", "([^"]+)"/g)) names.add(m[1]!);
  for (const m of text.matchAll(/code: "[A-Z-]+", name: "([^"]+)"/g)) names.add(m[1]!);
  const synth = readFileSync(join(E2E, "synth.ts"), "utf-8");
  const office = /office: "([^"]+)"/.exec(synth);
  if (office) names.add(office[1]!);
  names.delete(T.owner);
  return [...names];
}

function motion(reduced: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("reduce") ? reduced : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

beforeEach(() => {
  resetNav("/login");
  sessionStorage.clear();
  localStorage.clear();
  motion(false);
});

describe("the home page holds the sign-in form (decisions 1 and 7)", () => {
  it("one h1 with the hero heading, the card's h2 Sign In with its fields and Forgot password?", () => {
    renderWithClient(<HomePage />);
    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(T.home.heading);
    const card = document.getElementById("sign-in")!;
    expect(within(card).getByRole("heading", { level: 2, name: T.auth.signIn })).toBeInTheDocument();
    expect(within(card).getByLabelText(T.auth.email)).toHaveAttribute("type", "email");
    expect(within(card).getByLabelText(T.auth.password)).toHaveAttribute("type", "password");
    expect(within(card).getByRole("link", { name: T.auth.forgot })).toHaveAttribute("href", "/forgot");
  });

  it("the card has id sign-in inside main#main; there is no top bar, and the footer is outside main", () => {
    const { container } = renderWithClient(<HomePage />);
    const mains = container.querySelectorAll("main");
    expect(mains).toHaveLength(1);
    const main = mains[0]!;
    expect(main).toHaveAttribute("id", "main");
    expect(main).toContainElement(document.getElementById("sign-in"));
    // design home-page-refinements, decision 2: no header before main, and no banner landmark at all
    expect(main.previousElementSibling).toBeNull();
    expect(container.querySelector("header")).toBeNull();
    expect(screen.queryByRole("banner")).toBeNull();
    const footer = screen.getByRole("contentinfo");
    expect(main).not.toContainElement(footer);
  });
});

describe("one sign-in and one primary action (row 274, decision 10; refinements, decision 2)", () => {
  it("one form, only the submit is primary, and no Sign In link anywhere", () => {
    const { container } = renderWithClient(<HomePage />);
    expect(container.querySelectorAll("form")).toHaveLength(1);
    expect(container.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
    expect(primaryActions(container)).toEqual([T.auth.signIn]);
    expect(screen.queryAllByRole("link", { name: T.auth.signIn })).toHaveLength(0);
    expect(container.querySelector("a[href='#sign-in']")).toBeNull();
    const card = document.getElementById("sign-in")!;
    for (const el of container.querySelectorAll<HTMLElement>("button, a")) {
      if (/sign in/i.test(el.textContent ?? "")) expect(card).toContainElement(el);
    }
  });

  it("there is no closing band: the regions are the hero, the samples and the strip", () => {
    renderWithClient(<HomePage />);
    expect(screen.queryByRole("region", { name: "Sign in to ASLMS" })).toBeNull();
    const regions = screen.getAllByRole("region").map((r) => r.getAttribute("aria-labelledby"));
    expect(regions).toEqual(["home-heading", "home-samples", "home-strip"]);
  });
});

describe("the hero is the first screen (refinements, decision 1)", () => {
  it("holds the emblem, Government of Assam, the full name, the lead and the access line", () => {
    renderWithClient(<HomePage />);
    expect(screen.getAllByRole("img", { name: T.brand.emblemAlt })).toHaveLength(1);
    const hero = screen.getByRole("region", { name: T.home.heading });
    expect(hero).toHaveAttribute("data-first-screen");
    expect(within(hero).getByRole("img", { name: T.brand.emblemAlt })).toBeInTheDocument();
    expect(within(hero).getByText(T.owner)).toBeInTheDocument();
    expect(within(hero).getByText(T.portalLong)).toBeInTheDocument();
    expect(within(hero).getByText(T.home.lead)).toBeInTheDocument();
    expect(within(hero).getByText(T.home.access)).toBeInTheDocument();
  });

  it("at its foot a link, never a button, to the sample pictures", () => {
    renderWithClient(<HomePage />);
    const hero = screen.getByRole("region", { name: T.home.heading });
    const cue = within(hero).getByRole("link", { name: T.home.cue });
    expect(cue).toHaveAttribute("href", "#samples");
    expect(cue).not.toHaveAttribute("data-variant");
    const samples = screen.getByRole("region", { name: T.home.samples.heading });
    expect(samples).toHaveAttribute("id", "samples");
    expect(within(samples).getByText(T.home.samples.intro)).toBeInTheDocument();
  });
});

describe("the sample pictures are the real screens with sample data (refinements, decisions 3 and 4)", () => {
  const pictures = () => [
    screen.getByRole("img", { name: T.home.samples.inboxAria }),
    screen.getByRole("img", { name: T.home.samples.assistantAria }),
  ];

  it("both are role=img with a label around an inert, aria-hidden window with no link, field, button or heading", () => {
    renderWithClient(<HomePage />);
    for (const picture of pictures()) {
      expect(picture.children).toHaveLength(1);
      const window = picture.firstElementChild as HTMLElement;
      expect(window).toHaveAttribute("inert");
      expect(window).toHaveAttribute("aria-hidden", "true");
      expect(window.querySelectorAll("a, button, input, select, textarea, [tabindex], h1, h2, h3")).toHaveLength(0);
    }
  });

  it("each picture shows Sample Data in its caption bar", () => {
    renderWithClient(<HomePage />);
    for (const picture of pictures()) {
      expect(within(picture.parentElement!).getByText(T.home.samples.sampleLabel)).toBeInTheDocument();
    }
    expect(screen.getAllByText(T.home.samples.sampleLabel)).toHaveLength(2);
  });

  it("the Case Inbox picture is the With Me screen: the side menu, the four tabs and the kit table with its columns", () => {
    renderWithClient(<HomePage />);
    const window = pictures()[0]!.firstElementChild as HTMLElement;
    for (const label of [T.nav.dashboard, T.nav.inbox, T.nav.claim, T.nav.causelist, T.nav.assistant]) {
      expect(within(window).getAllByText(label).length, label).toBeGreaterThan(0);
    }
    for (const tab of [T.tabs.inbox.withMe, T.tabs.inbox.mine, T.tabs.inbox.sent, T.tabs.inbox.department]) {
      expect(within(window).getAllByText(tab).length, tab).toBeGreaterThan(0);
    }
    const table = window.querySelector("table")!;
    expect(table.className).toMatch(/dataTable/);
    const headers = [...table.querySelectorAll("thead th")].map((th) => th.textContent);
    expect(headers.slice(0, 4)).toEqual([T.files.case, T.inbox.nextHearingCol, T.files.action, T.cases.from]);
    expect(table.querySelectorAll("tbody tr")).toHaveLength(SAMPLE_ROWS.length);
    expect(SAMPLE_ROWS.length).toBeGreaterThanOrEqual(5);
  });

  it("the hearing badges carry row 190's colours: Tomorrow strong red, within a week soft amber, later plain", () => {
    const { container } = renderWithClient(<HomePage />);
    const badges = [...container.querySelectorAll("[data-shot='inbox'] [data-band]")];
    expect(badges.map((b) => b.getAttribute("data-band"))).toEqual(["tomorrow", "week", "week", "later", "none", "disposed"]);
    expect(badges[0]!.className).toMatch(/strong/);
    expect(badges[1]!.className).toMatch(/soft/);
    expect(badges[3]!.className).toMatch(/plain/);
  });

  it("the finished Assistant picture draws the answers as the Assistant does: the AI label, markers and Sources", () => {
    motion(true);
    renderWithClient(<HomePage />);
    const window = pictures()[1]!.firstElementChild as HTMLElement;
    expect(within(window).getAllByText(T.assistant.localModel)).toHaveLength(2);
    expect(within(window).getAllByText("S1").length).toBeGreaterThan(0);
    expect(within(window).getAllByText("S2").length).toBeGreaterThan(0);
    expect(within(window).getAllByText(T.assistant.courtGroup)).toHaveLength(2);
    expect(within(window).getAllByText(/^Order of .+, page 2$/).length).toBeGreaterThan(0);
  });
});

describe("no real identifier, department or court name on the page (row 274, decision 4; refinements, decision 4)", () => {
  it("the rendered text matches none of them, and every case number is masked", () => {
    motion(true);
    const { container } = renderWithClient(<HomePage />);
    const text = container.textContent ?? "";
    // no CNR and no unmasked case number
    expect(text).not.toMatch(/[A-Z]{4}\d{2}\d{6}\d{4}/);
    expect(text).not.toMatch(/\b[A-Z][A-Za-z.()]*\/\d+\/\d{4}\b/);
    const numbers = [...text.matchAll(/[A-Z][A-Za-z.()]*\/[^/\s]+\/\d{4}/g)].map((m) => m[0]);
    expect(numbers.length).toBeGreaterThanOrEqual(SAMPLE_ROWS.length);
    for (const n of numbers) expect(n, n).toMatch(/\/X+\//);
    // no figure: no number of five or more digits and no grouped thousands
    expect(text).not.toMatch(/\d{5,}/);
    expect(text).not.toMatch(/\d,\d{3}/);
    expect(text).not.toContain("Gauhati");
    expect(text).not.toContain(T.court);
    const names = fixtureOfficeNames();
    expect(names.length).toBeGreaterThan(5);
    for (const name of names) expect(text, name).not.toContain(name);
  });
});

describe("the strip (decision 4)", () => {
  it("has four items, and items 1, 2 and 4 are the frame's tiles word for word", () => {
    renderWithClient(<HomePage />);
    const strip = screen.getByRole("region", { name: T.home.strip.heading });
    const items = within(strip).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    const read = (li: HTMLElement) => ({
      title: within(li).getByRole("heading", { level: 3 }).textContent,
      text: li.querySelector("p")!.textContent,
    });
    const tiles = T.auth.frame.tiles;
    expect(read(items[0]!)).toEqual(tiles[0]);
    expect(read(items[1]!)).toEqual(tiles[1]);
    expect(read(items[2]!)).toEqual(T.home.strip.claim);
    expect(read(items[3]!)).toEqual(tiles[2]);
  });

  it("the footer carries its lines", () => {
    renderWithClient(<HomePage />);
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByText(T.home.footName)).toBeInTheDocument();
    expect(within(footer).getByText(T.auth.frame.foot)).toBeInTheDocument();
  });
});
