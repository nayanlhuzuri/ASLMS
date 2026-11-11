/**
 * The case Details labels (design portal-names-and-labels, decisions 17-19): every key the backend exports for the
 * overview (`enumCodes.json` → `case_detail_fields`) has a Title Case label or a place in `HIDDEN_FIELDS`, and no
 * label names a key the backend no longer sends.
 */
import { describe, expect, it } from "vitest";

import { caseFieldLabel, caseFieldValue, CASE_FIELD_LABELS, HIDDEN_FIELDS } from "./caseFields";
import codes from "./enumCodes.json";
import { isTitleCase } from "./titleCase";

const EXPORTED = new Set(Object.values(codes.case_detail_fields).flat());

describe("case Details labels", () => {
  it("labels or hides every key the overview can send", () => {
    const missing = [...EXPORTED].filter((k) => !(k in CASE_FIELD_LABELS) && !HIDDEN_FIELDS.has(k));
    expect(missing).toEqual([]);
  });

  it("writes every label in Title Case", () => {
    const bad = Object.entries(CASE_FIELD_LABELS).filter(([, label]) => !isTitleCase(label));
    expect(bad).toEqual([]);
  });

  it("keeps no stale label or hidden key", () => {
    expect(Object.keys(CASE_FIELD_LABELS).filter((k) => !EXPORTED.has(k))).toEqual([]);
    // `id` is the overview's own key, hidden by name should a block ever carry it (decision 17)
    expect([...HIDDEN_FIELDS].filter((k) => k !== "id" && !EXPORTED.has(k))).toEqual([]);
  });

  it("names the documented fields plainly", () => {
    expect(caseFieldLabel("cnr")).toBe("CNR");
    expect(caseFieldLabel("reg_no")).toBe("Registration Number");
    expect(caseFieldLabel("date_filing_disp")).toBe("Filing Disposal Date");
    expect(caseFieldLabel("goshwara_no")).toBe("Goshwara Number");
    expect(caseFieldLabel("uniform_code")).toBe("National Police Station Code");
  });

  it("names coded values", () => {
    expect(caseFieldValue("status", "pending")).toBe("Pending");
    expect(caseFieldValue("status", "P", "applications")).toBe("Pending");
    expect(caseFieldValue("status", "D", "applications")).toBe("Disposed");
    expect(caseFieldValue("first_seen_source", "causelist")).toBe("Cause List");
    expect(caseFieldValue("level", "trial", "lower_courts")).toBe("Trial Court");
    expect(caseFieldValue("level", "appellate", "lower_courts")).toBe("Lower Court");
    expect(caseFieldValue("reg_no", 3600)).toBe(3600);
    expect(caseFieldValue("status", null)).toBeNull();
  });
});
