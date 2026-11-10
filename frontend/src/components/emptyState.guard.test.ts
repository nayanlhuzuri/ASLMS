/**
 * The empty-state guard (design portal-ui-kit-fixes, decisions 17 and 31). Lists and panels show the kit `EmptyState`
 * (compact inside cards and panels), never a plain muted line; the main list of a page or a case tab gives it a title.
 * A plain muted line is allowed only as a value inside a fact list, and the few other exceptions below say why.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(process.cwd(), "src", "components");

function files(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name !== "ui") out.push(...files(full));
    } else if (name.endsWith(".tsx") && !name.endsWith(".test.tsx")) out.push(full);
  }
  return out;
}

const SOURCES = files(ROOT).map((f) => ({ path: relative(ROOT, f).replace(/\\/g, "/"), text: readFileSync(f, "utf-8") }));

/** A `DataTable` empty given as a bare paragraph or span. */
const BARE_EMPTY = /empty=\{<(p|span)\b/;

/** An empty branch (`… === 0 ? (` or `… === 0 ? <p`) that shows a paragraph with a muted class. */
const MUTED_BRANCH = /=== 0 \?\s*\(?\s*<p className=(?:"muted"|\{[a-z]+\.(?:muted|line|hint)\})/;

/** [file, the muted text's message key, the reason]: not an empty list, so not an empty state. */
const ALLOWED: [string, string, string][] = [
  ["data/AutomaticCollection.tsx", "T.dc.shareOffNote", "a setting's state (the discovery share is off), not an empty list"],
];

/** Decision 17(b): the main list of each page and case tab, and the title its empty state carries. */
const TITLED: [string, string][] = [
  ["files/Held.tsx", "EMPTY_TITLE[scope]"],
  ["inbox/MyCases.tsx", "T.inbox.nothingWaiting"],
  ["files/Sent.tsx", "T.files.emptySentTitle"],
  ["inbox/DepartmentCases.tsx", "T.inbox.nothingWaiting"],
  ["claim/Recommended.tsx", "T.inbox.nothingWaiting"],
  ["claim/Pool.tsx", "T.inbox.nothingWaiting"],
  ["claim/Transfers.tsx", "T.inbox.nothingWaiting"],
  ["alerts/AlertList.tsx", "T.alerts.emptyTitle"],
  ["nextdates/ReviewList.tsx", "T.nd.emptyTitle"],
  ["causelist/CauseList.tsx", "T.causelist.noEntriesTitle"],
  ["search/Search.tsx", "T.search.noneTitle"],
  ["search/CourtSearch.tsx", "T.search.noneTitle"],
  ["case/Orders.tsx", "T.case.noOrdersTitle"],
  ["case/Hearings.tsx", "T.case.noHearingsTitle"],
  ["case/Documents.tsx", "T.case.noDocumentsTitle"],
  ["case/Notes.tsx", "T.case.noNotesTitle"],
  ["workflow/CustodyTab.tsx", "T.wf.noLegsTitle"],
  ["case/Timeline.tsx", "T.case.noTimelineTitle"],
  ["case/Links.tsx", "T.case.noLinksTitle"],
  ["workflow/CaseAlerts.tsx", "T.wf.noAlertsTitle"],
  ["audit/AuditSearch.tsx", "T.audit.emptyTitle"],
  ["admin/Users.tsx", "T.users.emptyTitle"],
  ["admin/Offices.tsx", "T.offices.emptyTitle"],
  ["admin/Designations.tsx", "T.designations.emptyTitle"],
  ["admin/Tickets.tsx", "T.tickets.emptyTitle"],
  ["data/ProblemsAndFixes.tsx", "T.pf.failedNoneTitle"],
  ["data/ProblemsAndFixes.tsx", "T.pf.dupNoneTitle"],
  ["assistant/Assistant.tsx", "A.noConversationsTitle"],
];

function mutedBranches(text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(new RegExp(MUTED_BRANCH.source, "g"))) {
    const rest = text.slice(m.index! + m[0].length, m.index! + m[0].length + 200);
    out.push(/\{([A-Za-z.]+)\}/.exec(rest)?.[1] ?? rest.slice(0, 40));
  }
  return out;
}

describe("the empty-state guard (design portal-ui-kit-fixes, decision 31)", () => {
  it("checks itself", () => {
    expect(BARE_EMPTY.test('empty={<p className="muted">{T.x}</p>}')).toBe(true);
    expect(BARE_EMPTY.test("empty={<EmptyState compact>{T.x}</EmptyState>}")).toBe(false);
    expect(mutedBranches('{rows.length === 0 ? (\n  <p className="muted">{T.case.none}</p>')).toEqual(["T.case.none"]);
    expect(mutedBranches("{n === 0 ? <p className={ds.line}>{T.dc.x}</p> : null}")).toEqual(["T.dc.x"]);
    expect(mutedBranches("{rows.length === 0 ? (\n  <EmptyState compact>{T.case.none}</EmptyState>")).toEqual([]);
  });

  it("finds no DataTable empty given as a bare paragraph or span", () => {
    expect(SOURCES.filter((s) => BARE_EMPTY.test(s.text)).map((s) => s.path)).toEqual([]);
  });

  it("finds no empty-list branch that shows a muted paragraph", () => {
    const bad = SOURCES.flatMap((s) =>
      mutedBranches(s.text)
        .filter((key) => !ALLOWED.some(([path, k]) => path === s.path && k === key))
        .map((key) => `${s.path}: ${key}`),
    );
    expect(bad).toEqual([]);
  });

  it("every allowed exception still exists and says why", () => {
    for (const [path, key, reason] of ALLOWED) {
      const source = SOURCES.find((s) => s.path === path);
      expect(source && mutedBranches(source.text), path).toContain(key);
      expect(reason.length).toBeGreaterThan(10);
    }
  });

  it.each(TITLED)("the main list of %s has a titled empty state (%s)", (path, title) => {
    const source = SOURCES.find((s) => s.path === path);
    expect(source, path).toBeDefined();
    const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    expect(source!.text).toMatch(new RegExp(`<EmptyState[^>]*\\btitle=\\{${escaped}\\}`));
  });
});
