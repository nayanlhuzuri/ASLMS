import { describe, expect, it } from "vitest";

import { canViewInline, INLINE_PDF, pdfDownloadOnly, textLabel } from "./documents";

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

describe("textLabel (document-ocr, decision 3)", () => {
  it("names each text state in plain words", () => {
    expect(textLabel({ text_status: "pending", mime: "application/pdf" })).toBe("Being Read");
    expect(textLabel({ text_status: "extracted", mime: WORD })).toBe("Searchable");
    expect(textLabel({ text_status: "failed", mime: "application/pdf" })).toBe("Text Could Not Be Read");
  });

  it("a document with no text is scanned for PDFs and images, old Word for .doc, empty otherwise", () => {
    expect(textLabel({ text_status: "none", mime: "application/pdf" })).toBe("Scanned, Not Read");
    expect(textLabel({ text_status: "none", mime: "image/jpeg" })).toBe("Scanned, Not Read");
    expect(textLabel({ text_status: "none", mime: "image/png" })).toBe("Scanned, Not Read");
    expect(textLabel({ text_status: "none", mime: "application/msword" })).toBe("Old Word Format, Not Read");
    expect(textLabel({ text_status: "none", mime: WORD })).toBe("No text in the file");
    expect(textLabel({ text_status: "none", mime: null })).toBe("No text in the file");
  });
});
