/**
 * The public home page (design home-page, row 274, decisions 4, 5, 7 and 10): it holds the sign-in form, has one
 * primary action, shows the emblem and the frame's names in its hero, a plainly sample and inert picture of the app,
 * the four-item strip, and no identifier, count, department or court name anywhere.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { T } from "@/lib/messages";
import { resetNav } from "@/test/nav";
import { primaryActions, renderWithClient } from "@/test/render";

import { HomePage } from "./HomePage";

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

  it("the card has id sign-in inside main#main; the header and the footer are outside main", () => {
    const { container } = renderWithClient(<HomePage />);
    const mains = container.querySelectorAll("main");
    expect(mains).toHaveLength(1);
    const main = mains[0]!;
    expect(main).toHaveAttribute("id", "main");
    expect(main).toContainElement(document.getElementById("sign-in"));
    const header = screen.getByRole("banner");
    const footer = screen.getByRole("contentinfo");
    expect(main).not.toContainElement(header);
    expect(main).not.toContainElement(footer);
    expect(header.contains(main) || footer.contains(main)).toBe(false);
  });
});

describe("one primary action (decision 10)", () => {
  it("only the submit is primary; the two Sign In links are secondary and point to #sign-in", () => {
    const { container } = renderWithClient(<HomePage />);
    expect(container.querySelectorAll("[data-variant='primary']")).toHaveLength(1);
    expect(primaryActions(container)).toEqual([T.auth.signIn]);
    const links = screen.getAllByRole("link", { name: T.auth.signIn });
    expect(links).toHaveLength(2);
    for (const link of links) {
      expect(link).toHaveAttribute("href", "#sign-in");
      expect(link).not.toHaveAttribute("data-variant");
      expect(link.className).toMatch(/secondary/);
    }
    expect(screen.getByRole("banner")).toContainElement(links[0]!);
  });
});

describe("the hero has the emblem and the frame's names (decision 7)", () => {
  it("one emblem image, Government of Assam and the full name", () => {
    renderWithClient(<HomePage />);
    expect(screen.getAllByRole("img", { name: T.brand.emblemAlt })).toHaveLength(1);
    const hero = screen.getByRole("region", { name: T.home.heading });
    expect(within(hero).getByRole("img", { name: T.brand.emblemAlt })).toBeInTheDocument();
    expect(within(hero).getByText(T.owner)).toBeInTheDocument();
    expect(within(hero).getByText(T.portalLong)).toBeInTheDocument();
    expect(within(hero).getByText(T.home.lead)).toBeInTheDocument();
    expect(within(hero).getByText(T.home.access)).toBeInTheDocument();
  });
});

describe("the preview is plainly sample and inert (decision 5)", () => {
  it("one role=img with the sample label, the visible sample line, and nothing live inside", () => {
    renderWithClient(<HomePage />);
    const picture = screen.getByRole("img", { name: T.home.preview.aria });
    expect(picture).toBeInTheDocument();
    expect(within(picture).getByText(T.home.preview.windowLabel)).toBeInTheDocument();
    const window = picture.firstElementChild as HTMLElement;
    expect(window).toHaveAttribute("inert");
    expect(window).toHaveAttribute("aria-hidden", "true");
    expect(window.querySelectorAll("a, button, input, select, textarea, table, [tabindex]")).toHaveLength(0);
    for (const row of T.home.preview.rows) {
      expect(within(picture).getByText(row.name)).toBeInTheDocument();
      expect(within(picture).getByText(row.hearing)).toBeInTheDocument();
    }
    expect(within(picture).getByText(T.home.preview.sourceChip)).toBeInTheDocument();
  });

  it("the hearing badges carry the hearing colours' meaning: tomorrow danger, in 3 days warning", () => {
    renderWithClient(<HomePage />);
    const badge = (text: string) => screen.getByText(text).closest("[data-ui='badge']")!;
    expect(badge("Tomorrow").className).toMatch(/badge-danger/);
    expect(badge("In 3 Days").className).toMatch(/badge-warning/);
    expect(badge("Next Week").className).not.toMatch(/badge-(danger|warning)/);
  });
});

describe("no identifiers, counts, departments or court name on the page (decision 4)", () => {
  it("the rendered text matches none of them", () => {
    const { container } = renderWithClient(<HomePage />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/\b[A-Z][A-Za-z.()]*\/\d+\/\d{4}\b/);
    expect(text).not.toMatch(/\b[A-Z]{4}\d{12}\b/);
    expect(text).not.toMatch(/\d[\d,]{3,}/);
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

  it("the closing band and the footer carry their lines", () => {
    renderWithClient(<HomePage />);
    const closing = screen.getByRole("region", { name: T.home.closing.heading });
    expect(within(closing).getByText(T.home.closing.line)).toBeInTheDocument();
    expect(within(closing).getByRole("link", { name: T.auth.signIn })).toHaveAttribute("href", "#sign-in");
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByText(T.home.footName)).toBeInTheDocument();
    expect(within(footer).getByText(T.auth.frame.foot)).toBeInTheDocument();
  });
});
