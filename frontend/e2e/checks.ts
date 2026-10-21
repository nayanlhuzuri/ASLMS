/**
 * The geometry checks of the browser check (design portal-ui-polish, decision 21), run inside the page through
 * `page.evaluate`. The function is self-contained (no import is available in the page) and returns plain findings.
 *
 * - page overflow: `documentElement` or `body` wider than the viewport;
 * - inner sideways scrolling: an `overflow-x: auto | scroll` element that scrolls, outside a `data-scroll-x` region
 *   (the `Tabs` row and `ReportView`'s region carry it);
 * - off-screen content: a visible element whose right edge is past the viewport, outside such a region;
 * - clipped content (review of 21 Oct 2026): an `overflow-x: hidden | clip` box whose content is wider than it
 *   (`scrollWidth > clientWidth`), or a visible element past such a box's right edge, outside a `data-scroll-x`
 *   region. Two kinds of box are not clippers: a visually hidden one (1 px, or `clip: rect(…)`), and deliberate
 *   truncation with `text-overflow: ellipsis` (a badge, a nav label: the full text stays the title or accessible name);
 * - sizes (decision 14): a kit `Button` not 36 px tall (30 px for `sm`), a kit text input or select not 36 px, and at
 *   375 px any button or link drawn as a button shorter than 36 px except `sm` toolbars inside rows;
 * - alignment (decision 15): within one list, leading elements of one `data-lead` kind of unequal width;
 * - one primary (decision 16): more than one visible primary outside an open dialog.
 */

export interface PageFinding {
  kind: "page-overflow" | "inner-scroll" | "off-screen" | "clipped" | "size" | "alignment" | "primary";
  element: string;
  detail: string;
}

export interface CheckArgs {
  width: number;
}

/** Runs in the browser. */
export function pageChecks({ width }: CheckArgs): PageFinding[] {
  const out: PageFinding[] = [];
  const vw = document.documentElement.clientWidth;

  function describe(el: Element): string {
    const tag = el.tagName.toLowerCase();
    const id = el.id ? `#${el.id}` : "";
    const ui = el.getAttribute("data-ui") ? `[data-ui=${el.getAttribute("data-ui")}]` : "";
    const cls = (typeof el.className === "string" ? el.className : "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((c) => `.${c}`)
      .join("");
    const label = el.getAttribute("aria-label") ?? (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 48);
    return `${tag}${id}${ui}${cls}${label ? ` "${label}"` : ""}`;
  }

  function visible(el: Element): boolean {
    const box = el.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return false;
    const check = (el as Element & { checkVisibility?: (o?: object) => boolean }).checkVisibility;
    if (check && !check.call(el, { checkOpacity: true, checkVisibilityCSS: true })) return false;
    return true;
  }

  const scrollRegion = (el: Element) => !!el.closest("[data-scroll-x]");

  // page overflow
  for (const el of [document.documentElement, document.body]) {
    if (el.scrollWidth > el.clientWidth + 1) {
      out.push({ kind: "page-overflow", element: el.tagName.toLowerCase(), detail: `scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}` });
    }
  }

  const all = Array.from(document.body.querySelectorAll("*"));

  // inner sideways scrolling
  for (const el of all) {
    const ox = getComputedStyle(el).overflowX;
    if ((ox === "auto" || ox === "scroll") && el.scrollWidth > el.clientWidth + 1 && !scrollRegion(el) && visible(el)) {
      out.push({ kind: "inner-scroll", element: describe(el), detail: `scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}` });
    }
  }

  // off-screen content: the outermost element past the right edge, not clipped by an ancestor
  const reported: Element[] = [];
  for (const el of all) {
    if (scrollRegion(el) || !visible(el)) continue;
    const box = el.getBoundingClientRect();
    if (box.right <= vw + 1) continue;
    if (getComputedStyle(el).position === "fixed" && box.left >= vw) continue; // a closed off-canvas drawer
    let clipped = false;
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
      const ox = getComputedStyle(a).overflowX;
      if (ox !== "visible" && a.getBoundingClientRect().right <= vw + 1) {
        clipped = true;
        break;
      }
    }
    if (clipped || reported.some((r) => r.contains(el))) continue;
    reported.push(el);
    out.push({ kind: "off-screen", element: describe(el), detail: `right edge ${Math.round(box.right)} > viewport ${vw}` });
  }

  // clipped content: nothing may be cut off by an `overflow: hidden | clip` box, at any width
  const clipCache = new Map<Element, boolean>();
  function clipper(el: Element): boolean {
    let v = clipCache.get(el);
    if (v === undefined) {
      const cs = getComputedStyle(el);
      const box = el.getBoundingClientRect();
      v =
        (cs.overflowX === "hidden" || cs.overflowX === "clip") &&
        cs.textOverflow !== "ellipsis" &&
        box.width > 2 &&
        box.height > 2 &&
        (cs.clip === "auto" || cs.clip === "") &&
        !scrollRegion(el);
      clipCache.set(el, v);
    }
    return v;
  }
  const innerRight = (el: Element) => el.getBoundingClientRect().left + el.clientLeft + el.clientWidth;
  const clippedBy = new Set<Element>();
  for (const el of all) {
    if (!clipper(el) || !visible(el)) continue;
    if (el.scrollWidth > el.clientWidth + 1) {
      clippedBy.add(el);
      out.push({ kind: "clipped", element: describe(el), detail: `overflow-x ${getComputedStyle(el).overflowX}: scrollWidth ${el.scrollWidth} > clientWidth ${el.clientWidth}` });
    }
  }
  for (const el of all) {
    if (scrollRegion(el) || !visible(el) || getComputedStyle(el).position === "fixed") continue;
    let a = el.parentElement;
    while (a && a !== document.body && !clipper(a)) a = a.parentElement;
    if (!a || a === document.body || clippedBy.has(a)) continue;
    const right = el.getBoundingClientRect().right;
    const edge = innerRight(a);
    if (right > edge + 1) {
      clippedBy.add(a);
      out.push({ kind: "clipped", element: describe(el), detail: `right edge ${Math.round(right)} past ${describe(a)} at ${Math.round(edge)}` });
    }
  }

  // sizes (decision 14)
  const near = (a: number, b: number) => Math.abs(a - b) <= 0.5;
  const inRow = (el: Element) => !!el.closest("tr, li, [role='row'], [role='listitem']");
  for (const el of Array.from(document.querySelectorAll("[data-ui='button']"))) {
    if (!visible(el)) continue;
    const size = el.getAttribute("data-size");
    if (!size) continue; // the link variant draws as text
    const h = el.getBoundingClientRect().height;
    const want = size === "sm" ? 30 : 36;
    if (!near(h, want)) out.push({ kind: "size", element: describe(el), detail: `height ${h.toFixed(1)} px, want ${want}` });
    else if (width <= 375 && size === "sm" && !inRow(el)) {
      out.push({ kind: "size", element: describe(el), detail: `an sm button outside a row on a phone (${h.toFixed(1)} px < 36)` });
    }
  }
  for (const el of Array.from(document.querySelectorAll("[data-ui='field']"))) {
    if (!visible(el) || el.tagName === "TEXTAREA") continue;
    const h = el.getBoundingClientRect().height;
    if (!near(h, 36)) out.push({ kind: "size", element: describe(el), detail: `height ${h.toFixed(1)} px, want 36` });
  }
  if (width <= 375) {
    for (const el of Array.from(document.querySelectorAll(".button-link, a[class*='button']"))) {
      if (!visible(el) || el.getAttribute("data-ui")) continue;
      const h = el.getBoundingClientRect().height;
      if (h < 35.5 && !inRow(el)) out.push({ kind: "size", element: describe(el), detail: `a link drawn as a button, ${h.toFixed(1)} px < 36` });
    }
  }

  // alignment (decision 15): one list = the nearest list or table around the leading elements
  const groups = new Map<Element, Map<string, { el: Element; w: number }[]>>();
  for (const el of Array.from(document.querySelectorAll("[data-lead]"))) {
    if (!visible(el)) continue;
    const list = el.closest("ul, ol, table, [role='list']") ?? el.parentElement?.parentElement;
    if (!list) continue;
    const kind = el.getAttribute("data-lead")!;
    const byKind = groups.get(list) ?? new Map();
    const items = byKind.get(kind) ?? [];
    items.push({ el, w: el.getBoundingClientRect().width });
    byKind.set(kind, items);
    groups.set(list, byKind);
  }
  for (const [list, byKind] of groups) {
    for (const [kind, items] of byKind) {
      const widths = items.map((i) => i.w);
      if (Math.max(...widths) - Math.min(...widths) > 0.5) {
        out.push({ kind: "alignment", element: describe(list), detail: `data-lead="${kind}" widths ${widths.map((w) => w.toFixed(1)).join(", ")}` });
      }
    }
  }

  // one primary (decision 16)
  const primaries = Array.from(document.querySelectorAll("[data-variant='primary'], .button-link")).filter(
    (el) => visible(el) && !el.closest("[role='dialog']"),
  );
  if (primaries.length > 1) {
    out.push({ kind: "primary", element: primaries.map(describe).join(" | "), detail: `${primaries.length} primary actions outside a dialog` });
  }
  return out;
}
