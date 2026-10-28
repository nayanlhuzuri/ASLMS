/**
 * The browser check (design portal-ui-polish, decisions 18-22). Every page route read from `src/app` at run time (as
 * `backend/tools/portal_smoke.py` reads it), at 375, 768 and 1280 px, against the real `web` service, with a dummy
 * session cookie that passes the page gate (the public pages go without it) and every `/api/backend/**` and
 * `/api/session/**` request answered in the browser from the fixtures. The interaction states as well. Each page
 * gets a full-page screenshot and the geometry checks of `checks.ts`; a page fails on any finding, a missing fixture,
 * a request other than `GET`, or a console or page error.
 */
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { pageChecks, type PageFinding } from "./checks";
import { answer, SAMPLE, type ACTIVITY_DEFAULT } from "./fixtures";
import { OLD_CASE_REF_PATH } from "./fixtures/legacy";
import { kept, runDir, slug, writeResult, type Finding } from "./results";

const APP = join(__dirname, "..", "src", "app");
const PUBLIC = new Set(["/login", "/login/code", "/forgot", "/forgot/code"]);

/** The page routes of `src/app` (route groups left out, dynamic segments filled from the fixtures' samples). */
function routes(dir = APP): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "api") out.push(...routes(path));
    } else if (name === "page.tsx") {
      const parts = relative(APP, dir)
        .split(sep)
        .filter((p) => p && !(p.startsWith("(") && p.endsWith(")")));
      const filled = parts.map((p, i) => {
        if (!p.startsWith("[")) return p;
        const parent = parts[i - 1];
        if (parent === "tickets") return SAMPLE.ticketRefPath;
        if (parent === "users") return SAMPLE.userId;
        if (parent === "audit") return SAMPLE.auditId;
        if (parent === "offices") return SAMPLE.officeCode;
        if (parent === "orders") return SAMPLE.orderId;
        // design case-workspace-admin, decision 25: one user type's page
        if (parent === "access") return SAMPLE.userType;
        return SAMPLE.caseRefPath;
      });
      out.push("/" + filled.join("/"));
    }
  }
  return out.sort();
}

/**
 * The old Files and Cases list addresses and where they lead (design case-workspace-admin, decision 3; case-inbox-merge,
 * decision 12; `OLD_FILES_REDIRECTS` and `OLD_CASES_REDIRECTS` in `src/lib/routes.ts`, pinned by `routes.test.ts`): each
 * is checked as a redirect that lands on its Case inbox tab.
 */
const OLD_FILES: Record<string, string> = {
  "/files": "/inbox/working",
  "/files/mine": "/inbox/working",
  "/files/offices": "/inbox/working?held=offices",
  "/files/department": "/inbox/pending",
  "/files/sent": "/inbox/sent",
  "/inbox/files": "/inbox/working",
  "/cases/with-me": "/inbox/working",
  "/cases/sent": "/inbox/sent",
  "/cases/pending": "/inbox/pending",
  // design data-collection-redesign, decision 2 (`OLD_DATA_REDIRECTS`): the anchor is not part of the landed path
  "/data/load": "/data/automatic",
  "/data/discovery": "/data/automatic",
  "/data/fetch": "/data/collect",
};

interface Visit {
  findings: Finding[];
  redirect: string | null;
}

/**
 * Answers the page's API calls and collects problems and errors while `run` drives the page. `activity` changes the
 * session ping's answer (the session states, design session-timeout).
 */
async function watch(
  page: Page,
  name: string,
  width: number,
  publicPage: boolean,
  activity?: Partial<typeof ACTIVITY_DEFAULT>,
): Promise<(extra: () => Promise<void>) => Promise<Visit>> {
  const findings: Finding[] = [];
  const add = (kind: string, element: string, detail: string) => findings.push({ route: name, width, kind, element, detail });
  if (!publicPage) {
    const base = test.info().project.use.baseURL ?? "http://web:3000";
    await page.context().addCookies([
      { name: "aslms_at", value: "uicheck", url: base },
      { name: "aslms_rt", value: "uicheck", url: base },
    ]);
  }
  await page.route(/\/api\/(backend|session)\//, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const session = url.pathname.startsWith("/api/session/");
    const apiPath = url.pathname.replace(/^\/api\/backend/, "");
    const reply = session
      ? { status: 405, body: { detail: "the browser check never signs in" }, problem: `${request.method()} ${url.pathname}` }
      : answer(request.method(), url, apiPath, request.postData(), activity);
    if (reply.problem) add(reply.status === 404 ? "missing-fixture" : "not-get", reply.problem, `answered ${reply.status}`);
    await route.fulfill({ status: reply.status, contentType: "application/json", body: JSON.stringify(reply.body) });
  });
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    // a 404 or 405 the fixtures gave is already a finding of its own
    if (/^Failed to load resource/.test(text) && /\/api\/(backend|session)\//.test(msg.location().url)) return;
    add("console-error", text.slice(0, 200), msg.location().url);
  });
  page.on("pageerror", (err) => add("page-error", err.message.slice(0, 200), err.stack?.split("\n")[1]?.trim() ?? ""));

  return async (drive) => {
    await drive();
    await settle(page);
    const checks: PageFinding[] = await page.evaluate(pageChecks, { width });
    for (const c of checks) add(c.kind, c.element, c.detail);
    return { findings, redirect: null };
  };
}

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  await page.waitForTimeout(300);
}

async function shoot(page: Page, name: string, width: number): Promise<string> {
  const file = join(String(width), `${slug(name)}.png`);
  mkdirSync(join(runDir(), String(width)), { recursive: true });
  await page.screenshot({ path: join(runDir(), file), fullPage: true });
  return file.split(sep).join("/");
}

function widthOf(page: Page): number {
  return page.viewportSize()?.width ?? 0;
}

test.describe("every page", () => {
  for (const route of routes()) {
    test(route, async ({ page }) => {
      const width = widthOf(page);
      const run = await watch(page, route, width, PUBLIC.has(route));
      let redirect: string | null = null;
      const visit = await run(async () => {
        await page.goto(route);
      });
      await settle(page);
      const landed = new URL(page.url()).pathname;
      if (landed !== route) redirect = landed + new URL(page.url()).search;
      const findings = kept(visit.findings, redirect !== null);
      const screenshot = redirect ? null : await shoot(page, route, width);
      writeResult({ name: route, width, screenshot, redirect, findings });
      expect(findings, JSON.stringify(findings, null, 2)).toEqual([]);
      if (OLD_FILES[route]) expect(redirect, `${route} leads to its new place`).toBe(OLD_FILES[route]);
    });
  }
});

/**
 * Design case-ref-court-prefix, decision 20: an old case number in the address (a mail link sent before the
 * renumbering) opens the case and the portal replaces the address with the current number, keeping the tab and the
 * query. The fixtures answer any case path with the sample case, whose `ref_no` is the current number.
 */
test("an old case number lands on the current address", async ({ page }) => {
  const width = widthOf(page);
  const name = `/cases/${OLD_CASE_REF_PATH}/orders (old case number)`;
  const run = await watch(page, name, width, false);
  const visit = await run(async () => {
    await page.goto(`/cases/${OLD_CASE_REF_PATH}/orders?page=1`);
    await page.waitForURL((u) => u.pathname === `/cases/${SAMPLE.caseRefPath}/orders`);
  });
  const landed = new URL(page.url());
  const redirect = landed.pathname + landed.search;
  const findings = kept(visit.findings, true);
  writeResult({ name, width, screenshot: null, redirect, findings });
  expect(redirect).toBe(`/cases/${SAMPLE.caseRefPath}/orders?page=1`);
  expect(findings, JSON.stringify(findings, null, 2)).toEqual([]);
});

interface State {
  name: string;
  path: string;
  /** Only at these widths (default: all three). */
  widths?: number[];
  /** The session ping's answer for this state (design session-timeout). */
  activity?: Partial<typeof ACTIVITY_DEFAULT>;
  open: (page: Page) => Promise<void>;
}

const STATES: State[] = [
  {
    // design session-timeout, decision 17: idle 125 s with a 120 s warning, so the warning opens about 5 s after the load
    name: "/ (Session Warning)",
    path: "/",
    activity: { idle_seconds: 125, warning_seconds: 120, idle_ends_in: 125 },
    open: async (page) => {
      await page.getByRole("dialog", { name: "Are You Still There?" }).waitFor({ timeout: 15_000 });
    },
  },
  {
    // decision 18: the hard limit 125 s away, so the notice opens about 5 s after the load
    name: "/ (Session Ending Soon)",
    path: "/",
    activity: { session_ends_in: 125 },
    open: async (page) => {
      await page.getByRole("dialog", { name: "Session Ending Soon" }).waitFor({ timeout: 15_000 });
    },
  },
  {
    name: "/ (phone drawer open)",
    path: "/",
    widths: [375],
    open: async (page) => {
      await page.getByRole("button", { name: "Open Menu" }).click();
      await page.getByRole("dialog").first().waitFor();
    },
  },
  {
    // design portal-ui-polish-2, decision 14: the one-level side menu with Administration open
    name: "/ (side menu: Administration open)",
    path: "/",
    widths: [1280],
    open: async (page) => {
      const admin = page.getByRole("treeitem", { name: "Administration" });
      await admin.waitFor();
      await admin.focus();
      await page.keyboard.press("ArrowRight");
      await page.getByRole("group", { name: "Administration" }).getByRole("treeitem", { name: "Users" }).waitFor();
    },
  },
  {
    // decision 19: the phone drawer holds the same tree
    name: "/ (phone drawer: Administration open)",
    path: "/",
    widths: [375],
    open: async (page) => {
      await page.getByRole("button", { name: "Open Menu" }).click();
      await page.getByRole("dialog").first().waitFor();
      const admin = page.getByRole("treeitem", { name: "Administration" });
      await admin.focus();
      await page.keyboard.press("ArrowRight");
      await page.getByRole("group", { name: "Administration" }).getByRole("treeitem", { name: "Users" }).waitFor();
    },
  },
  {
    name: "/claim/recommended (case claim modal)",
    path: `/claim/recommended?case=${SAMPLE.caseRefPath}`,
    open: async (page) => {
      await page.getByRole("dialog").first().waitFor();
    },
  },
  {
    // design claim-assign-wording, decision 2: Claim pressed, so the claim step and its Assign Now row show (one line
    // at 1280 px, stacked at 375 px)
    name: "/claim/recommended (case claim modal, Assign Now)",
    path: `/claim/recommended?case=${SAMPLE.caseRefPath}`,
    open: async (page) => {
      const dialog = page.getByRole("dialog").first();
      await dialog.waitFor();
      await dialog.getByRole("button", { name: /^Claim( for .+)?$/ }).first().click();
      const pick = dialog.locator("select").filter({ has: page.locator("option", { hasText: "Choose a Department" }) });
      if ((await pick.count()) > 0) {
        const value = await pick.first().locator("option").nth(1).getAttribute("value");
        if (value) await pick.first().selectOption(value);
      }
      await dialog.getByRole("heading", { name: "Assign Now (Optional)" }).waitFor();
      await dialog.getByLabel("Dealing Officer").waitFor();
    },
  },
  {
    name: "/system (API card)",
    path: "/system?api=cnr",
    open: async (page) => {
      await page.getByRole("dialog").first().waitFor();
    },
  },
  {
    // design case-inbox-merge, decision 9: Working on's side panel, the remark read from the case's custody card
    name: "/inbox/working (side panel)",
    path: "/inbox/working",
    open: async (page) => {
      await page.locator("tbody tr").first().click();
      await page.getByRole("dialog").first().waitFor();
    },
  },
  {
    // decision 8: Show "With my offices", the held list inside Working on
    name: "/inbox/working?held=offices",
    path: "/inbox/working?held=offices",
    open: async (page) => {
      await page.getByRole("radiogroup", { name: "Show" }).waitFor();
      await page.locator("tbody tr").first().waitFor();
    },
  },
  {
    // design assistant, decision 11: the court-record view as opened from a citation of the reader's own answer
    name: `/assistant/orders/${SAMPLE.orderId} (court record from a citation)`,
    path: `/assistant/orders/${SAMPLE.orderId}?m=${SAMPLE.messageId}`,
    open: async (page) => {
      await page.getByRole("link", { name: "Open the Order" }).waitFor();
    },
  },
  // design assistant-polish, decision 16: an answer holding its markers (no inline list, no side panel), one source
  // opened from its marker, and every source of the answer from "Sources (n)"; decision 15: a quick fact
  {
    name: `/cases/${SAMPLE.caseRefPath}/assistant (answer with references)`,
    path: `/cases/${SAMPLE.caseRefPath}/assistant`,
    open: async (page) => {
      await page.getByRole("button", { name: /^Source S1:/ }).first().waitFor();
    },
  },
  {
    name: `/cases/${SAMPLE.caseRefPath}/assistant (source dialog)`,
    path: `/cases/${SAMPLE.caseRefPath}/assistant`,
    open: async (page) => {
      await page.getByRole("button", { name: /^Source S1:/ }).first().click();
      await page.getByRole("dialog", { name: "Source S1" }).waitFor();
    },
  },
  {
    name: `/cases/${SAMPLE.caseRefPath}/assistant (sources of this answer)`,
    path: `/cases/${SAMPLE.caseRefPath}/assistant`,
    open: async (page) => {
      await page.getByRole("button", { name: /^Sources \(\d+\)$/ }).first().click();
      await page.getByRole("dialog", { name: "Sources of This Answer" }).waitFor();
    },
  },
  {
    name: "/assistant (quick fact from the case record)",
    path: "/assistant",
    open: async (page) => {
      await page.getByText("From the Case Record").first().waitFor();
    },
  },
  {
    name: `/cases/${SAMPLE.caseRefPath} (send case, step 1)`,
    path: `/cases/${SAMPLE.caseRefPath}`,
    open: async (page) => {
      await page.getByRole("button", { name: "Send Case" }).first().click();
      await page.getByRole("dialog").first().waitFor();
    },
  },
  {
    // design claim-assign-wording, decision 3: the Assign dialog (from More Actions, present at every width), with a
    // department chosen so the Responsible Unit and Dealing Officer row shows
    name: `/cases/${SAMPLE.caseRefPath} (Assign dialog)`,
    path: `/cases/${SAMPLE.caseRefPath}`,
    open: async (page) => {
      await page.getByRole("button", { name: "More Actions" }).first().click();
      await page.getByRole("menuitem", { name: "Assign" }).click();
      const dialog = page.getByRole("dialog", { name: "Assign This Case" });
      await dialog.waitFor();
      const pick = dialog.getByLabel("For", { exact: true });
      if ((await pick.count()) > 0) {
        const value = await pick.locator("option").nth(1).getAttribute("value");
        if (value) await pick.selectOption(value);
      }
      await dialog.getByLabel("Dealing Officer").waitFor();
    },
  },
  {
    // design case-workspace-admin, decision 15: the remarks history on its own address
    name: `/cases/${SAMPLE.caseRefPath}?remarks=all (remarks panel)`,
    path: `/cases/${SAMPLE.caseRefPath}?remarks=all`,
    open: async (page) => {
      await page.getByRole("dialog", { name: "Remarks and Notes" }).waitFor();
      await page.getByText("Sent By", { exact: false }).first().waitFor();
    },
  },
  {
    // decision 8: below 1100 px the rail's cards sit under the header as collapsibles; every one opened
    name: `/cases/${SAMPLE.caseRefPath} (rail cards open)`,
    path: `/cases/${SAMPLE.caseRefPath}`,
    widths: [375, 768],
    open: async (page) => {
      const closed = page.locator("[data-rail='stacked'] button[aria-expanded='false']");
      await page.locator("[data-rail='stacked']").waitFor();
      for (let i = 0; i < 6 && (await closed.count()) > 0; i += 1) await closed.first().click();
    },
  },
  {
    // design portal-ui-polish-2, decision 28: the Office Picker open in the Users toolbar
    name: "/admin/users (Office Picker open)",
    path: "/admin/users",
    open: async (page) => {
      await page.getByRole("combobox", { name: "Office" }).click();
      await page.getByRole("listbox", { name: "Offices" }).waitFor();
    },
  },
  {
    // decision 27: More Filters open, with Include Logins Without an Active Office
    name: "/admin/users (More Filters open)",
    path: "/admin/users",
    open: async (page) => {
      await page.getByRole("button", { name: /^More Filters/ }).click();
      await page.getByLabel("Include Logins Without an Active Office").waitFor();
    },
  },
  {
    // decisions 31 and 34: the User Details modal on its own address, the Offices tab
    name: "/admin/users/<id> (User Details, Offices tab)",
    path: `/admin/users/${SAMPLE.userId}?tab=offices`,
    open: async (page) => {
      await page.getByRole("dialog").first().waitFor();
      await page.getByRole("list", { name: "Offices" }).waitFor();
    },
  },
  {
    // decision 34: an office card's Actions menu, End Membership last and in red
    name: "/admin/users/<id> (Actions menu open)",
    path: `/admin/users/${SAMPLE.userId}?tab=offices`,
    open: async (page) => {
      await page.getByRole("button", { name: /^Actions for / }).first().click();
      await page.getByRole("menuitem", { name: "End Membership" }).waitFor();
    },
  },
  {
    // decision 42: Recommended From Cause Lists beside the codes, each code with its picker and Map
    name: "/admin/mapping/codes (Recommended From Cause Lists)",
    path: "/admin/mapping/codes",
    open: async (page) => {
      await page.getByRole("complementary", { name: "Recommended From Cause Lists" }).waitFor();
      await page.getByRole("button", { name: /^Map / }).first().waitFor();
    },
  },
  {
    // design list-search, decisions 9-11: every unmapped code, three pages of 100 loaded inside the panel's box
    name: "/admin/mapping/codes (Recommended From Cause Lists: 300 of 1,066 loaded)",
    path: "/admin/mapping/codes",
    open: async (page) => {
      const panel = page.getByRole("complementary", { name: "Recommended From Cause Lists" });
      await panel.getByText("1,066 codes not mapped").waitFor();
      for (const shown of ["Showing 200 of 1,066", "Showing 300 of 1,066"]) {
        await panel.getByRole("button", { name: "Show 100 More" }).click();
        await panel.getByText(shown).waitFor();
      }
    },
  },
  {
    // design list-search, decision 39: Sort By Code, the toolbar naming the order
    name: "/admin/mapping/codes (Recommended: sorted by Code)",
    path: "/admin/mapping/codes",
    open: async (page) => {
      const panel = page.getByRole("complementary", { name: "Recommended From Cause Lists" });
      await panel.getByText("1,066 codes not mapped").waitFor();
      await panel.getByRole("combobox", { name: "Sort By" }).selectOption("code");
      await panel.getByText(/Sorted by Code, A to Z/).waitFor();
    },
  },
  {
    // design list-search, decision 11: a search with no match, with Clear Search
    name: "/admin/mapping/codes (Recommended: no matches)",
    path: "/admin/mapping/codes",
    open: async (page) => {
      const panel = page.getByRole("complementary", { name: "Recommended From Cause Lists" });
      await panel.getByText("1,066 codes not mapped").waitFor();
      await panel.getByRole("searchbox", { name: "Search Recommended Codes" }).fill("zzzz nothing");
      await panel.getByText("No matches for “zzzz nothing”.").waitFor();
    },
  },
  {
    // design list-search, decisions 13 and 33: the Counsel Codes sorted by Office (the Sort By select at 375 px)
    name: "/admin/mapping/codes (Counsel Codes sorted by Office)",
    path: "/admin/mapping/codes",
    open: async (page) => {
      const table = page.getByRole("table", { name: "Counsel Codes" });
      await table.waitFor();
      // the codes' own toolbar is the section's first; the Recommended panel below has a Sort By of its own
      const select = page.locator("section[aria-label='Counsel Codes'] [data-ui='list-toolbar']").first().getByRole("combobox", { name: "Sort By" });
      if ((await select.count()) > 0) await select.selectOption("office");
      else await table.getByRole("button", { name: "Office" }).click();
      await page.getByText(/Sorted by Office, A to Z/).first().waitFor();
    },
  },
  {
    // design list-search, decision 14: the keywords searched in the browser
    name: "/admin/mapping/keywords (search typed)",
    path: "/admin/mapping/keywords",
    open: async (page) => {
      await page.getByRole("table", { name: "Keywords and Name Patterns" }).or(page.getByText("Nothing here yet.")).first().waitFor();
      const box = page.getByRole("searchbox", { name: "Search Words" });
      if (await box.isVisible().catch(() => false)) await box.fill("education");
    },
  },
  {
    // design list-search, decision 17: Search Words on the first row of the Case inbox's own views
    name: "/inbox/working (Search Words on the first row)",
    path: "/inbox/working",
    open: async (page) => {
      await page.getByLabel(/^Words/).first().waitFor();
    },
  },
  {
    // decision 25: two switches changed, so the Save bar counts them
    name: `/admin/access/${SAMPLE.userType} (two switches changed, Save bar)`,
    path: `/admin/access/${SAMPLE.userType}`,
    open: async (page) => {
      const switches = page.locator("button[role='switch']:not([disabled])");
      await switches.first().waitFor();
      await switches.nth(0).click();
      await switches.nth(1).click();
      await page.getByText("2 unsaved changes").waitFor();
    },
  },
  {
    // design portal-ui-polish-2, decisions 21-24: Layout B on the Cause List with More Filters open (List Type, Court)
    name: "/causelist (More Filters open)",
    path: `/causelist?date=${SAMPLE.causelistDate}&bench_id=${SAMPLE.benchId}`,
    open: async (page) => {
      await page.getByRole("button", { name: /^More Filters/ }).click();
      await page.getByLabel("List Type").waitFor();
    },
  },
  {
    // decision 25: the View Cause List modal on its own address, the Printed Entries tab
    name: "/causelist (View Cause List modal, Printed Entries)",
    path: `/causelist?date=${SAMPLE.causelistDate}&bench_id=${SAMPLE.benchId}&view=${SAMPLE.benchId}&vtab=entries`,
    open: async (page) => {
      await page.getByRole("dialog").first().waitFor();
      await page.getByRole("dialog").getByRole("table").first().waitFor();
    },
  },
  {
    // decision 25: the same modal on the Original PDF tab (the list chooser, Download and the browser's viewer)
    name: "/causelist (View Cause List modal, Original PDF)",
    path: `/causelist?date=${SAMPLE.causelistDate}&bench_id=${SAMPLE.benchId}&view=${SAMPLE.benchId}&vtab=pdf`,
    open: async (page) => {
      await page.getByRole("dialog").first().waitFor();
      await page.getByRole("dialog").locator("iframe").waitFor();
    },
  },
  {
    // decisions 21-23: Search on Layout B (Search For as the hero)
    name: "/search (Layout B)",
    path: "/search",
    open: async (page) => {
      await page.getByRole("search", { name: "Filters" }).waitFor();
      await page.getByLabel("Search For").waitFor();
    },
  },
  {
    // decisions 23 and 28: the Audit Log on Layout B with the Office Picker open
    name: "/audit (Layout B with the Office Picker open)",
    path: "/audit",
    open: async (page) => {
      await page.getByRole("combobox", { name: "Office" }).click();
      await page.getByRole("listbox", { name: "Offices" }).waitFor();
    },
  },
  {
    // design portal-ui-polish-2, decision 13: Edit Name on the user-type page (the sample type has the 80-character name)
    name: `/admin/access/${SAMPLE.userType} (Edit Name dialog)`,
    path: `/admin/access/${SAMPLE.userType}`,
    open: async (page) => {
      await page.getByRole("button", { name: "Edit Name" }).click();
      await page.getByRole("dialog", { name: "Edit Name" }).waitFor();
    },
  },
  {
    // design office-head-picker, decision 11: New Office with a Department kind, the head section (a heading and a row)
    name: "/admin/offices/new (Department, head section)",
    path: "/admin/offices/new",
    open: async (page) => {
      await page.getByLabel("Kind").selectOption("department");
      await page.getByRole("region", { name: "Head of the Department" }).waitFor();
    },
  },
  {
    // decision 2: the User Picker open, with an offices line, a No Office Yet option and a greyed option
    name: "/admin/offices/new (User Picker open)",
    path: "/admin/offices/new",
    open: async (page) => {
      await page.getByLabel("Kind").selectOption("department");
      await page.getByRole("combobox", { name: "Person" }).fill("ri");
      await page.getByRole("listbox", { name: "People" }).getByRole("option").first().waitFor();
    },
  },
  {
    // design office-head-picker-followups, decision 5: the search failed (the fixture answers 500), so the list says
    // so with Try Again under it, never "No person matches"; the note and the button fit the list at 375 px
    name: "/admin/offices/new (User Picker search failed)",
    path: "/admin/offices/new",
    open: async (page) => {
      await page.getByLabel("Kind").selectOption("department");
      await page.getByRole("combobox", { name: "Person" }).fill("fail");
      await page.getByRole("listbox", { name: "People" }).getByText("The search did not work.").waitFor({ timeout: 15_000 });
      await page.getByRole("button", { name: "Try Again" }).waitFor();
    },
  },
  {
    // decision 10: the Reactivate dialog with the same head section (`?reactivate=1` opens it)
    name: `/admin/offices/${SAMPLE.officeCode} (Reactivate dialog)`,
    path: `/admin/offices/${SAMPLE.officeCode}?reactivate=1`,
    open: async (page) => {
      await page.getByRole("dialog", { name: "Reactivate" }).waitFor();
      await page.getByRole("dialog").getByRole("combobox", { name: "Person" }).waitFor();
    },
  },
  {
    // decision 9: the head-change request with the Incoming Head picker
    name: "/admin/tickets/new (Incoming Head)",
    path: `/admin/tickets/new?department=${SAMPLE.officeCode}&operation=set`,
    open: async (page) => {
      await page.getByRole("combobox", { name: "Incoming Head" }).waitFor();
    },
  },
  {
    // decision 15: New User for a new e-mail with No Office Yet ticked (`?no_office=1`)
    name: "/admin/users/new (No Office Yet ticked)",
    path: "/admin/users/new?no_office=1&return=%2Fadmin%2Foffices%2Fnew",
    open: async (page) => {
      await page.getByLabel("E-mail").fill("new.head@assam.gov.in");
      await page.getByRole("button", { name: "Check E-mail" }).click();
      await page.getByLabel("No Office Yet").waitFor();
    },
  },
  {
    // decision 17: the Users list with More Filters' No Office Yet on
    name: "/admin/users (No Office Yet filter)",
    path: "/admin/users?no_office=true",
    open: async (page) => {
      // a filter set under More Filters opens the panel on arrival (design portal-ui-polish-2-admin, `Users.tsx`), so
      // the button is pressed only while the panel is closed; pressing it again would close it
      const more = page.getByRole("button", { name: /^More Filters/ });
      await more.waitFor();
      if ((await more.getAttribute("aria-expanded")) !== "true") await more.click();
      await page.getByLabel("No Office Yet").waitFor();
    },
  },
  // design data-collection-redesign, round 1: the Overview live and Automatic Collection's dialogs and forms
  {
    name: "data-overview-running",
    path: "/data/overview",
    open: async (page) => {
      await page.getByRole("heading", { name: "Right Now" }).waitFor();
      await page.getByRole("table", { name: "Month by Month" }).waitFor();
    },
  },
  {
    name: "data-automatic-start-new",
    path: "/data/automatic",
    open: async (page) => {
      await page.getByRole("button", { name: "Start a Load" }).click();
      const dialog = page.getByRole("dialog", { name: "Start a Load" });
      await dialog.getByLabel("From").fill("2025-02-01");
      await dialog.getByLabel("To").fill("2025-02-05");
      await dialog.getByRole("button", { name: "Check These Dates" }).click();
      await dialog.getByRole("button", { name: "Start Load" }).waitFor();
    },
  },
  {
    name: "data-automatic-start-nothing-new",
    path: "/data/automatic",
    open: async (page) => {
      await page.getByRole("button", { name: "Start a Load" }).click();
      const dialog = page.getByRole("dialog", { name: "Start a Load" });
      await dialog.getByLabel("From").fill("2025-01-01");
      await dialog.getByLabel("To").fill("2025-01-05");
      await dialog.getByRole("button", { name: "Check These Dates" }).click();
      await dialog.getByText(/Nothing new to fetch/).waitFor();
    },
  },
  {
    name: "data-automatic-pause-dialog",
    path: "/data/automatic",
    open: async (page) => {
      await page.getByRole("button", { name: "Pause" }).click();
      await page.getByRole("dialog", { name: "Pause the Past-Months Collection" }).getByLabel(/Why Pause It/).fill("quota for searches");
    },
  },
  {
    name: "data-automatic-priority",
    path: "/data/automatic",
    open: async (page) => {
      const form = page.getByRole("form", { name: "What Goes First" });
      await form.scrollIntoViewIfNeeded();
      await form.getByLabel(/^Reason/).fill("verification of the order");
    },
  },
  {
    name: "data-automatic-no-department-names",
    path: "/data/automatic#department-names",
    open: async (page) => {
      await page.getByText(/No department names are registered yet/).waitFor();
    },
  },
  // design next-hearing-highlight: the next hearing badge in every band, as a table at 1280 px and as cards below
  {
    name: "/inbox/working (next hearing bands)",
    path: "/inbox/working",
    open: async (page) => {
      for (const band of ["today", "tomorrow", "week", "later", "passed", "none", "disposed"]) {
        await page.locator(`[data-band="${band}"]`).first().waitFor();
      }
      await expect(page.locator('[data-band="today"]').first()).toBeVisible();
      await expect(page.locator('[data-band="passed"]').first()).toBeVisible();
    },
  },
  {
    name: "/ (upcoming hearings bands)",
    path: "/",
    open: async (page) => {
      const list = page.getByRole("list", { name: "Upcoming Hearings" });
      await list.waitFor();
      await expect(list.locator('[data-band="today"]').first()).toBeVisible();
      await expect(list.locator('[data-band="tomorrow"]').first()).toBeVisible();
    },
  },
  {
    name: `/cases/${SAMPLE.caseRefPath} (next hearing header and next date from orders)`,
    path: `/cases/${SAMPLE.caseRefPath}`,
    open: async (page) => {
      await expect(page.getByRole("region", { name: "Case Summary" }).locator('[data-band="tomorrow"]').first()).toBeVisible();
      const card = page.getByRole("region", { name: "Next Date From Orders" });
      await card.scrollIntoViewIfNeeded();
      await expect(card.locator('[data-kind="suggested"]').first()).toBeVisible();
    },
  },
];

test.describe("interaction states", () => {
  for (const state of STATES) {
    test(state.name, async ({ page }) => {
      const width = widthOf(page);
      test.skip(!!state.widths && !state.widths.includes(width), "not at this width");
      const run = await watch(page, state.name, width, false, state.activity);
      const visit = await run(async () => {
        await page.goto(state.path);
        await settle(page);
        await state.open(page);
      });
      const screenshot = await shoot(page, state.name, width);
      writeResult({ name: state.name, width, screenshot, redirect: null, findings: visit.findings });
      expect(visit.findings, JSON.stringify(visit.findings, null, 2)).toEqual([]);
    });
  }
});
