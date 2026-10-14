import { describe, expect, it } from "vitest";

import { istDay } from "./format";
import { cellText, checkPeriod, choiceOf, exportUrl, periodChoice, reportParams, scopeLabel } from "./reports";

describe("periodChoice (IST dates)", () => {
  it("this month on the first is one day, on the 14th the first to the 14th", () => {
    expect(periodChoice("this_month", "2026-10-01")).toEqual({ from: "2026-10-01", to: "2026-10-01" });
    expect(periodChoice("this_month", "2026-10-14")).toEqual({ from: "2026-10-01", to: "2026-10-14" });
  });

  it("last month across a year end and across month lengths", () => {
    expect(periodChoice("last_month", "2027-01-05")).toEqual({ from: "2026-12-01", to: "2026-12-31" });
    expect(periodChoice("last_month", "2026-03-31")).toEqual({ from: "2026-02-01", to: "2026-02-28" });
    expect(periodChoice("last_month", "2026-10-14")).toEqual({ from: "2026-09-01", to: "2026-09-30" });
  });

  it("this year, the last 7 and the last 30 days include today", () => {
    expect(periodChoice("this_year", "2026-10-14")).toEqual({ from: "2026-01-01", to: "2026-10-14" });
    expect(periodChoice("last_7", "2026-10-14")).toEqual({ from: "2026-10-08", to: "2026-10-14" });
    expect(periodChoice("last_30", "2026-10-14")).toEqual({ from: "2026-09-15", to: "2026-10-14" });
    expect(periodChoice("custom", "2026-10-14")).toBeNull();
  });

  it("uses the IST day near midnight UTC", () => {
    // 19:00 UTC on 30 Sep is 00:30 IST on 1 Oct
    const today = istDay(new Date("2026-09-30T19:00:00Z"));
    expect(today).toBe("2026-10-01");
    expect(periodChoice("this_month", today)).toEqual({ from: "2026-10-01", to: "2026-10-01" });
    expect(periodChoice("last_month", today)).toEqual({ from: "2026-09-01", to: "2026-09-30" });
    // 18:00 UTC on 31 Dec is 23:30 IST, still 31 Dec
    const eve = istDay(new Date("2026-12-31T18:00:00Z"));
    expect(periodChoice("this_year", eve)).toEqual({ from: "2026-01-01", to: "2026-12-31" });
  });

  it("names the quick choice the URL's dates stand for", () => {
    expect(choiceOf("hearings-disposals", "2026-10-01", "2026-10-14", "2026-10-14")).toBe("this_month");
    expect(choiceOf("hearings-disposals", "2026-09-01", "2026-09-30", "2026-10-14")).toBe("last_month");
    expect(choiceOf("hearings-disposals", "2026-09-03", "2026-09-30", "2026-10-14")).toBe("custom");
    expect(choiceOf("data-health", undefined, undefined, "2026-10-14")).toBe("last_7");
    expect(choiceOf("data-health", "2026-09-15", "2026-10-14", "2026-10-14")).toBe("last_30");
  });
});

describe("checkPeriod", () => {
  it("refuses a missing date, an end before the start and a start after today", () => {
    expect(checkPeriod(undefined, "2026-10-01", "2026-10-14")).toBe("missing");
    expect(checkPeriod("2026-10-01", "", "2026-10-14")).toBe("missing");
    expect(checkPeriod("2026-10-05", "2026-10-01", "2026-10-14")).toBe("order");
    expect(checkPeriod("2026-10-15", "2026-10-16", "2026-10-14")).toBe("future");
  });

  it("never checks the length of the range (the server's setting)", () => {
    expect(checkPeriod("2020-01-01", "2026-10-14", "2026-10-14")).toBeNull();
    expect(checkPeriod("2026-10-14", "2026-10-14", "2026-10-14")).toBeNull();
  });
});

describe("reportParams", () => {
  const today = "2026-10-14";

  it("fills the defaults per report", () => {
    expect(reportParams("pending-cases", {}, today)).toEqual({});
    expect(reportParams("hearings-disposals", {}, today)).toEqual({ from: "2026-10-01", to: "2026-10-14" });
    expect(reportParams("pending-actions", {}, today)).toEqual({});
    expect(reportParams("data-health", {}, today)).toEqual({});
  });

  it("keeps the URL's values and omits empty ones", () => {
    expect(reportParams("hearings-disposals", { department: "EDU", from: "2026-01-01", to: "2026-02-01" }, today)).toEqual({
      department: "EDU",
      from: "2026-01-01",
      to: "2026-02-01",
    });
    expect(reportParams("pending-cases", { department: "", offset: "50" }, today)).toEqual({});
    expect(reportParams("pending-actions", { holder_department: "", department: "EDU" }, today)).toEqual({ department: "EDU" });
  });

  it("sends include_cases only when ticked", () => {
    expect(reportParams("pending-actions", { include_cases: "true", holder_department: "HEALTH" }, today)).toEqual({
      include_cases: "true",
      holder_department: "HEALTH",
    });
    expect(reportParams("pending-actions", { include_cases: "false" }, today)).toEqual({});
    expect(reportParams("pending-cases", { include_cases: "true" }, today)).toEqual({});
  });

  it("never sends a department with data-health", () => {
    expect(reportParams("data-health", { department: "EDU", from: "2026-09-15", to: "2026-10-14" }, today)).toEqual({
      from: "2026-09-15",
      to: "2026-10-14",
    });
  });
});

describe("exportUrl", () => {
  it("carries the same parameters plus format, encoded, under the relay", () => {
    expect(exportUrl("pending-actions", { department: "EDU", include_cases: "true" }, "xlsx")).toBe(
      "/api/backend/reports/pending-actions?department=EDU&include_cases=true&format=xlsx",
    );
    expect(exportUrl("pending-cases", { department: "A&B" }, "pdf")).toBe(
      "/api/backend/reports/pending-cases?department=A%26B&format=pdf",
    );
    expect(exportUrl("data-health", {}, "pdf")).toBe("/api/backend/reports/data-health?format=pdf");
  });
});

describe("cellText", () => {
  it("formats by kind", () => {
    expect(cellText(128400, "int")).toBe("1,28,400");
    expect(cellText(12, "days")).toBe("12");
    expect(cellText("2026-10-01", "date")).toBe("1 Oct 2026");
    expect(cellText("WP(C)/1/2026", "text")).toBe("WP(C)/1/2026");
    expect(cellText(null, "int")).toBe("—");
    expect(cellText("", "text")).toBe("—");
    expect(cellText(undefined, "date")).toBe("—");
  });
});

describe("scopeLabel", () => {
  const departments = [{ code: "EDU", name: "Education", is_active: true }];
  it("names the scope as the API returned it", () => {
    expect(scopeLabel({ scope: "state", department_code: null }, departments)).toBe("Whole State");
    expect(scopeLabel({ scope: "department", department_code: "EDU" }, departments)).toBe("Education (EDU)");
    expect(scopeLabel({ scope: "department", department_code: "FIN" }, departments)).toBe("FIN");
  });
});
