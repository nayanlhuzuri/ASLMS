/**
 * Which files the portal opens in the browser (design portal-cases-followups, decisions 9 and 10). View is offered only
 * for types a browser shows itself: PDFs (while `INLINE_PDF` is true) and images. Everything else, Word included, is
 * download-only; the list is an allowlist, so a type not named here stays download-only until it is. The API's inline
 * disposition and its `Content-Security-Policy: sandbox` and `nosniff` headers are unchanged; no browser sniffing.
 */

import { T } from "@/lib/messages";

/**
 * PDFs open inline through the relay under the API's sandbox header. The owner's decision at approval (12 Oct 2026):
 * true by default; set to false if Chrome's or Firefox's own viewer does not render the sandboxed PDF, and PDFs then
 * offer Download only, with the hint "Opens as a download".
 */
export const INLINE_PDF = true;

function baseType(mime: string | null | undefined): string {
  return (mime ?? "").split(";")[0]!.trim().toLowerCase();
}

export function isPdf(mime: string | null | undefined): boolean {
  return baseType(mime) === "application/pdf";
}

/** True when View (inline) is offered for the type. */
export function canViewInline(mime: string | null | undefined, inlinePdf: boolean = INLINE_PDF): boolean {
  const m = baseType(mime);
  if (m === "application/pdf") return inlinePdf;
  return m.startsWith("image/");
}

/** True when a PDF is download-only because inline PDFs are switched off (the screen shows the hint). */
export function pdfDownloadOnly(mime: string | null | undefined, inlinePdf: boolean = INLINE_PDF): boolean {
  return isPdf(mime) && !inlinePdf;
}

/**
 * The text line of a document in plain words (design document-ocr, decision 3), never the raw `text_status`:
 * `pending` "Being read", `extracted` "Searchable", `none` on a PDF or an image "Scanned, not read", on an old Word
 * file "Old Word format, not read", on anything else (an empty Word file) "No text in the file", `failed` "Text
 * could not be read". No OCR in Phase 1 (the owner's decision of 20 Oct 2026).
 */
export function textLabel(doc: { text_status: string; mime?: string | null }): string {
  const labels = T.case.textLabels;
  const m = baseType(doc.mime);
  switch (doc.text_status) {
    case "pending":
      return labels.pending!;
    case "extracted":
      return labels.extracted!;
    case "failed":
      return labels.failed!;
    case "none":
      if (m === "application/pdf" || m === "image/jpeg" || m === "image/png") return labels.scanned!;
      if (m === "application/msword") return labels.oldWord!;
      return labels.noText!;
    default:
      return doc.text_status; // a state added later shows as sent until it gets words
  }
}
