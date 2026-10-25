/**
 * The browser check (design portal-ui-polish, decisions 18-22). Every page route read from `src/app` at run time (as
 * `backend/tools/portal_smoke.py` reads it), at 375, 768 and 1280 px, against the real `web` service, with a dummy
 * session cookie that passes the page gate (the public pages go without it) and every `/api/backend/**` and
 * `/api/session/**` request answered in the browser from the fixtures. Five interaction states as well. Each page
 * gets a full-page screenshot and the geometry checks of `checks.ts`; a page fails on any finding, a missing fixture,
 * a request other than `GET`, or a console or page error.
 */
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { pageChecks, type PageFinding } from "./checks";
import { answer, SAMPLE } from "./fixtures";
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
};

interface Visit {
  findings: Finding[];
  redirect: string | null;
}

/** Answers the page's API calls and collects problems and errors while `run` drives the page. */
async function watch(page: Page, name: string, width: number, publicPage: boolean): Promise<(extra: () => Promise<void>) => Promise<Visit>> {
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
      : answer(request.method(), url, apiPath);
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
      if (OLD_FILES[route]) expect(redirect, `${route} leads to its Case inbox tab`).toBe(OLD_FILES[route]);
    });
  }
});

interface State {
  name: string;
  path: string;
  /** Only at these widths (default: all three). */
  widths?: number[];
  open: (page: Page) => Promise<void>;
}

const STATES: State[] = [
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
  {
    name: `/cases/${SAMPLE.caseRefPath} (send case, step 1)`,
    path: `/cases/${SAMPLE.caseRefPath}`,
    open: async (page) => {
      await page.getByRole("button", { name: "Send Case" }).first().click();
      await page.getByRole("dialog").first().waitFor();
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
    // design portal-ui-polish-2, decision 13: Edit Name on the user-type page (the sample type has the 80-character name)
    name: `/admin/access/${SAMPLE.userType} (Edit Name dialog)`,
    path: `/admin/access/${SAMPLE.userType}`,
    open: async (page) => {
      await page.getByRole("button", { name: "Edit Name" }).click();
      await page.getByRole("dialog", { name: "Edit Name" }).waitFor();
    },
  },
];

test.describe("interaction states", () => {
  for (const state of STATES) {
    test(state.name, async ({ page }) => {
      const width = widthOf(page);
      test.skip(!!state.widths && !state.widths.includes(width), "not at this width");
      const run = await watch(page, state.name, width, false);
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
