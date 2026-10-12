import { describe, expect, it } from "vitest";

import { canViewInline, INLINE_PDF, pdfDownloadOnly } from "./documents";

const WORD = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

describe("canViewInline", () => {
  it("PDFs open inline by default (the owner's decision at approval)", () => {
    expect(INLINE_PDF).toBe(true);
    expect(canViewInline("application/pdf")).toBe(true);
    expect(canViewInline("Application/PDF; charset=binary")).toBe(true);
    expect(pdfDownloadOnly("application/pdf")).toBe(false);
  });

  it("images open inline; Word, unknown and missing types are download-only", () => {
    expect(canViewInline("image/png")).toBe(true);
    expect(canViewInline("image/jpeg")).toBe(true);
    expect(canViewInline(WORD)).toBe(false);
    expect(canViewInline("application/msword")).toBe(false);
    expect(canViewInline("text/html")).toBe(false);
    expect(canViewInline("application/x-new-type")).toBe(false);
    expect(canViewInline(null)).toBe(false);
    expect(canViewInline("")).toBe(false);
  });

  it("with inline PDFs switched off, a PDF is download-only with the hint; images keep View", () => {
    expect(canViewInline("application/pdf", false)).toBe(false);
    expect(pdfDownloadOnly("application/pdf", false)).toBe(true);
    expect(canViewInline("image/png", false)).toBe(true);
    expect(pdfDownloadOnly("image/png", false)).toBe(false);
    expect(pdfDownloadOnly(WORD, false)).toBe(false);
  });
});
