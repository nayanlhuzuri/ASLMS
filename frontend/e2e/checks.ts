/**
 * The geometry checks of the browser check (design portal-ui-polish, decision 21), run inside the page through
 * `page.evaluate`. The function is self-contained (no import is available in the page) and returns plain findings.
 *
 * - page overflow: `documentElement` or `body` wider than the viewport;
 * - inner sideways scrolling: an `overflow-x: auto | scroll` element that scrolls, outside a `data-scroll-x` region
 *   (the `Tabs` row, `ReportView`'s region and the kit `CodeBlock` carry it; the third by the owner's decision of
 *   28 Oct 2026, amending decision 21: sideways scrolling is right for code);
 * - off-screen content: a visible element whose right edge is past the viewport, outside such a region;
 * - clipped content (review of 21 Oct 2026): an `overflow-x: hidden | clip` box whose content is wider than it
 *   (`scrollWidth > clientWidth`), or a visible element past such a box's right edge, outside a `data-scroll-x`
 *   region. Three kinds of box are not clippers: a visually hidden one (1 px, or `clip: rect(…)`), deliberate
 *   truncation with `text-overflow: ellipsis` (a badge, a nav label: the full text stays the title or accessible name),
 *   and a text field (a `textarea`, or an `input` of type text, search, email, url, tel or password), which scrolls its
 *   own value by nature (owner, 28 Oct 2026);
 * - sizes (decision 14): a kit `Button` not 36 px tall (30 px for `sm`), a kit text input or select not 36 px, and at
 *   375 px any button or link drawn as a button shorter than 36 px except `sm` toolbars inside rows;
 * - alignment (decision 15): within one list, leading elements of one `data-lead` kind of unequal width;
 * - field rows (owner, 23 Oct 2026): in a flex or grid row holding labelled fields, the items on one line must share
 *   the top of their labels and the top of their boxes (input, select, textarea, or a bare button beside them), so a
 *   hint under one field can never push its neighbours out of line; and (design portal-ui-polish-2, decision 26) an
 *   item whose control is a checkbox sits level with the boxes: its checkbox's vertical centre within 1 px of the line's
 *   box centre (the 36 px control line), not with the labels;
 * - one primary (decision 16): more than one visible primary outside an open dialog;
 * - gutter (design data-collection-redesign, decision 12): `main#main` keeps at least 12 px of left padding, and no
 *   visible element inside it reaches past its content box, unless it sits in a `[data-scroll-x]` or `[data-bleed]`
 *   region, is fixed or absolute (or inside such a box), is visually hidden, or is clipped by a box of its own;
 * - doubled heading (decision 12): a visible `h1`-`h4`, `caption` or `legend` whose normalised text equals the nearest
 *   visible heading above it in the same `section`, `article`, `[data-ui=card]` or `[role=dialog]`;
 * - menu clipped (design case-inbox-simplify, decision 23): for any open `[role='menu']`, each `[role='menuitem']` must
 *   lie fully inside the viewport and be the element at its own centre (or hold it), so no scrolling box cuts it off and
 *   nothing covers it. With no menu open it costs nothing.
 * - caption inset (design portal-ui-kit-fixes, decisions 1, 2 and 24): a visible `caption` not marked
 *   `data-caption="heading"` starts its first line of text within 2 px of the content-box left of its table's first
 *   visible header cell when the table is drawn as a table; when the table is a block (cards) the caption is at least
 *   90% of the table's width, so it is never squeezed to its longest word;
 * - date wrap (decision 24, K5): in `main#main`, a day-month-year date ("23 Oct 2026") whose text runs over more than
 *   one line;
 * - broken word (decision 24, DC1): in `main#main`, outside `[data-scroll-x]`, `pre`, `code`, `[data-free-text]` and
 *   visually hidden boxes, a word of four or more letters only, or a number of four or more digits and commas, whose
 *   text runs over more than one line (a word with a hyphen, slash or dot has legal break points and is not tested);
 * - card row (decision 24, K6): in a table drawn as cards (a block `table` whose cells carry `data-label`), a visible
 *   labelled cell with nothing in its value (no text, link, button, field, image or meter) is an empty row, and within
 *   one card the values' left edges are equal within 1 px.
 */

/**
 * The kinds the geometry checks raise. A page that redirected is measured on the page it landed on, so only these are
 * dropped then (design followups-oct, decision 22); `missing-fixture`, `not-get`, `console-error` and `page-error` are
 * kept. `pageChecks` runs inside the browser and must not read this constant.
 */
export const GEOMETRY_KINDS = [
  "page-overflow",
  "inner-scroll",
  "off-screen",
  "clipped",
  "size",
  "alignment",
  "primary",
  "gutter",
  "doubled-heading",
  "menu-clipped",
  "caption-inset",
  "date-wrap",
  "broken-word",
  "card-row",
] as const;

export interface PageFinding {
  kind: (typeof GEOMETRY_KINDS)[number];
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
  const TEXT_INPUT_TYPES = ["text", "search", "email", "url", "tel", "password"];
  // a text field scrolls its own value (owner, 28 Oct 2026): only these, nothing else is exempt
  const textField = (el: Element): boolean =>
    el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && TEXT_INPUT_TYPES.includes((el as HTMLInputElement).type));
  const clipCache = new Map<Element, boolean>();
  function clipper(el: Element): boolean {
    let v = clipCache.get(el);
    if (v === undefined) {
      const cs = getComputedStyle(el);
      const box = el.getBoundingClientRect();
      v =
        !textField(el) &&
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

  // field rows (owner, 23 Oct 2026): items on one line of a row of labelled fields share label tops and box tops
  const boxOf = (child: Element): Element | null => {
    if (child.matches("button, a[data-ui=button]")) return child;
    const box = child.querySelector("input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea");
    return box && visible(box) ? box : null;
  };
  const rows = new Set<Element>();
  for (const label of Array.from(document.querySelectorAll("label"))) {
    const row = label.parentElement?.parentElement;
    if (!row || !visible(label)) continue;
    const display = getComputedStyle(row).display;
    if (display.includes("flex") || display.includes("grid")) rows.add(row);
  }
  const checkboxOf = (child: Element): HTMLInputElement | null => {
    if (boxOf(child)) return null;
    const box = child.querySelector<HTMLInputElement>("input[type=checkbox]");
    return box && visible(box) ? box : null;
  };
  for (const row of rows) {
    const items = Array.from(row.children).filter((c) => visible(c) && boxOf(c));
    const checks = Array.from(row.children).filter((c) => visible(c) && checkboxOf(c));
    // the checkbox step: a checkbox item on the line of a box sits on the box's centre line
    for (const check of checks) {
      const r = check.getBoundingClientRect();
      const line = items.filter((i) => {
        const o = i.getBoundingClientRect();
        return r.top < o.bottom && o.top < r.bottom;
      });
      if (line.length === 0) continue;
      const box = boxOf(line[0]!)!.getBoundingClientRect();
      const boxCentre = box.top + box.height / 2;
      const c = checkboxOf(check)!.getBoundingClientRect();
      const checkCentre = c.top + c.height / 2;
      if (Math.abs(checkCentre - boxCentre) > 1) {
        out.push({
          kind: "alignment",
          element: describe(row),
          detail: `field row: checkbox centre ${checkCentre.toFixed(1)} vs box centre ${boxCentre.toFixed(1)}`,
        });
      }
    }
    if (items.length < 2) continue;
    // one visual line = items whose boxes overlap vertically
    const lines: Element[][] = [];
    for (const item of items) {
      const b = boxOf(item)!.getBoundingClientRect();
      const line = lines.find((l) => {
        const o = boxOf(l[0]!)!.getBoundingClientRect();
        return b.top < o.bottom && o.top < b.bottom;
      });
      if (line) line.push(item);
      else lines.push([item]);
    }
    for (const line of lines) {
      if (line.length < 2) continue;
      const boxTops = line.map((i) => boxOf(i)!.getBoundingClientRect().top);
      if (Math.max(...boxTops) - Math.min(...boxTops) > 1) {
        out.push({ kind: "alignment", element: describe(row), detail: `field row: box tops ${boxTops.map((t) => t.toFixed(1)).join(", ")}` });
        continue;
      }
      const labels = line.map((i) => i.querySelector("label")).filter((l): l is HTMLLabelElement => !!l && visible(l));
      const labelTops = labels.map((l) => l.getBoundingClientRect().top);
      if (labelTops.length > 1 && Math.max(...labelTops) - Math.min(...labelTops) > 1) {
        out.push({ kind: "alignment", element: describe(row), detail: `field row: label tops ${labelTops.map((t) => t.toFixed(1)).join(", ")}` });
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

  // a visually hidden element (1 px, or `clip: rect(…)`) is not drawn
  function srOnly(el: Element): boolean {
    const box = el.getBoundingClientRect();
    if (box.width <= 1 && box.height <= 1) return true;
    const clip = getComputedStyle(el).clip;
    return !!clip && clip !== "auto" && /rect\(\s*0(px)?[ ,]+0(px)?[ ,]+0(px)?[ ,]+0(px)?\s*\)/.test(clip);
  }

  // the gutter (design data-collection-redesign, decision 12)
  const main = document.querySelector("main#main");
  if (main) {
    const cs = getComputedStyle(main);
    const pad = parseFloat(cs.paddingLeft) || 0;
    if (pad < 12) out.push({ kind: "gutter", element: describe(main), detail: `left padding ${pad.toFixed(1)} px < 12` });
    const mbox = main.getBoundingClientRect();
    const left = mbox.left + (parseFloat(cs.borderLeftWidth) || 0) + pad;
    const right = mbox.right - (parseFloat(cs.borderRightWidth) || 0) - (parseFloat(cs.paddingRight) || 0);
    const exempt = (el: Element): boolean => {
      for (let cur: Element | null = el; cur && cur !== main; cur = cur.parentElement) {
        if (cur.matches("[data-scroll-x], [data-bleed]")) return true;
        const st = getComputedStyle(cur);
        if (st.position === "fixed" || st.position === "absolute") return true;
        if (cur !== el && st.overflowX !== "visible") return true; // clipped by a box of its own, measured as that box
        if (srOnly(cur)) return true;
      }
      return false;
    };
    let reported = 0;
    for (const el of Array.from(main.querySelectorAll("*"))) {
      if (reported >= 3) break;
      if (!visible(el) || exempt(el)) continue;
      const box = el.getBoundingClientRect();
      if (box.left < left - 0.5 || box.right > right + 0.5) {
        out.push({
          kind: "gutter",
          element: describe(el),
          detail: `box ${Math.round(box.left)}-${Math.round(box.right)} outside the content box ${Math.round(left)}-${Math.round(right)}`,
        });
        reported += 1;
      }
    }
  }

  // doubled headings (decision 12)
  const norm = (el: Element) => (el.textContent ?? "").trim().replace(/\s+/g, " ").toLowerCase();
  const heads = Array.from(document.querySelectorAll("h1, h2, h3, h4, caption, legend")).filter((el) => visible(el) && !srOnly(el));
  for (let i = 0; i < heads.length; i += 1) {
    const el = heads[i]!;
    const box = el.parentElement?.closest("section, article, [data-ui=card], [role=dialog]");
    if (!box || !norm(el)) continue;
    let above: Element | null = null;
    for (let j = i - 1; j >= 0; j -= 1) {
      if (box.contains(heads[j]!)) {
        above = heads[j]!;
        break;
      }
    }
    if (above && norm(above) === norm(el)) {
      out.push({ kind: "doubled-heading", element: describe(el), detail: `repeats ${describe(above)}` });
    }
  }

  // menus (design case-inbox-simplify, decision 23): every item of an open menu fully on screen and not covered
  const vh = document.documentElement.clientHeight;
  for (const menu of Array.from(document.querySelectorAll("[role='menu']"))) {
    for (const item of Array.from(menu.querySelectorAll("[role='menuitem']"))) {
      const box = item.getBoundingClientRect();
      if (box.width === 0 || box.height === 0) {
        out.push({ kind: "menu-clipped", element: describe(item), detail: "an item of an open menu has no size" });
        continue;
      }
      if (box.left < 0 || box.top < 0 || box.right > vw + 0.5 || box.bottom > vh + 0.5) {
        out.push({
          kind: "menu-clipped",
          element: describe(item),
          detail: `box ${Math.round(box.left)},${Math.round(box.top)}-${Math.round(box.right)},${Math.round(box.bottom)} outside the viewport ${vw}x${vh}`,
        });
        continue;
      }
      const at = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      if (!at || !(at === item || item.contains(at))) {
        out.push({ kind: "menu-clipped", element: describe(item), detail: `covered or cut off: ${at ? describe(at) : "nothing"} at its centre` });
      }
    }
  }

  // a box hidden from sight on purpose (visually hidden, or inside such a box)
  function hiddenBox(el: Element | null): boolean {
    for (let cur = el; cur && cur !== document.body; cur = cur.parentElement) if (srOnly(cur)) return true;
    return false;
  }

  /** The distinct line tops of a range's text (rects of no width are left out; 2 px apart is another line). */
  function lineCount(range: Range): number {
    const tops: number[] = [];
    for (const r of Array.from(range.getClientRects())) {
      if (r.width < 0.5 || r.height < 0.5) continue;
      if (!tops.some((t) => Math.abs(t - r.top) <= 2)) tops.push(r.top);
    }
    return tops.length;
  }

  // caption inset (design portal-ui-kit-fixes, decisions 1, 2 and 24)
  for (const cap of Array.from(document.querySelectorAll("caption"))) {
    if (cap.getAttribute("data-caption") === "heading" || !visible(cap) || hiddenBox(cap)) continue;
    const table = cap.closest("table");
    if (!table || !visible(table)) continue;
    const display = getComputedStyle(table).display;
    if (display === "table" || display === "inline-table") {
      const cell = Array.from(table.querySelectorAll("thead th, tbody th, tbody td")).find((c) => visible(c) && !hiddenBox(c));
      if (!cell) continue;
      const range = document.createRange();
      range.selectNodeContents(cap);
      const first = Array.from(range.getClientRects()).find((r) => r.width > 0.5);
      if (!first) continue;
      const cs = getComputedStyle(cell);
      const contentLeft = cell.getBoundingClientRect().left + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.paddingLeft) || 0);
      if (Math.abs(first.left - contentLeft) > 2) {
        out.push({
          kind: "caption-inset",
          element: describe(cap),
          detail: `caption text at ${first.left.toFixed(1)}, column text at ${contentLeft.toFixed(1)}`,
        });
      }
    } else {
      const cw = cap.getBoundingClientRect().width;
      const tw = table.getBoundingClientRect().width;
      if (cw < 0.9 * tw) {
        out.push({ kind: "caption-inset", element: describe(cap), detail: `caption ${cw.toFixed(1)} px wide in a ${tw.toFixed(1)} px table drawn as cards` });
      }
    }
  }

  // the text nodes of the page body, for the date and word rules
  const SKIP_TEXT = "script, style, textarea, select, option, noscript";
  function textNodes(root: Element, skip: string): Text[] {
    const nodes: Text[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const parent = n.parentElement;
      if (!parent || !n.textContent || !n.textContent.trim()) continue;
      if (parent.closest(skip) || !visible(parent) || hiddenBox(parent)) continue;
      nodes.push(n as Text);
    }
    return nodes;
  }

  if (main) {
    // date wrap (decision 24, K5): a date never breaks inside itself
    const DATE = /\d{1,2}[  ][A-Z][a-z]{2}[  ]\d{4}/g;
    let dates = 0;
    for (const node of textNodes(main, SKIP_TEXT)) {
      if (dates >= 5) break;
      for (const m of node.textContent!.matchAll(DATE)) {
        const range = document.createRange();
        range.setStart(node, m.index!);
        range.setEnd(node, m.index! + m[0].length);
        if (lineCount(range) > 1) {
          out.push({ kind: "date-wrap", element: describe(node.parentElement!), detail: `"${m[0]}" runs over more than one line` });
          dates += 1;
        }
      }
    }

    // broken word (decision 24, DC1): words and numbers break only between them
    const EDGE = /^[("'“‘[]+|[)"'”’\],.;:!?]+$/g;
    const WORD = /^(?:[A-Za-z]{4,}|[\d,]{4,})$/;
    let words = 0;
    for (const node of textNodes(main, `${SKIP_TEXT}, [data-scroll-x], pre, code, [data-free-text]`)) {
      if (words >= 5) break;
      for (const m of node.textContent!.matchAll(/\S+/g)) {
        const token = m[0].replace(EDGE, "");
        if (!WORD.test(token)) continue;
        const start = m.index! + m[0].indexOf(token);
        const range = document.createRange();
        range.setStart(node, start);
        range.setEnd(node, start + token.length);
        if (lineCount(range) > 1) {
          out.push({ kind: "broken-word", element: describe(node.parentElement!), detail: `"${token}" is broken over more than one line` });
          words += 1;
          if (words >= 5) break;
        }
      }
    }
  }

  // card row (decision 24, K6): a card draws no empty row, and its values start at one x
  const FILLED = "a, button, input, select, img, svg, progress, meter";
  for (const table of Array.from(document.querySelectorAll("table"))) {
    if (getComputedStyle(table).display !== "block" || !table.querySelector("td[data-label]") || !visible(table)) continue;
    for (const tr of Array.from(table.querySelectorAll("tr"))) {
      const lefts: { cell: Element; left: number }[] = [];
      for (const td of Array.from(tr.querySelectorAll(":scope > td[data-label]"))) {
        if (!visible(td) || hiddenBox(td)) continue;
        if (!(td.textContent ?? "").trim() && !td.querySelector(FILLED)) {
          out.push({ kind: "card-row", element: describe(td), detail: `an empty "${td.getAttribute("data-label")}" row on a card` });
          continue;
        }
        const range = document.createRange();
        range.selectNodeContents(td);
        const box = range.getBoundingClientRect();
        if (box.width > 0) lefts.push({ cell: td, left: box.left });
      }
      if (lefts.length > 1) {
        const xs = lefts.map((l) => l.left);
        if (Math.max(...xs) - Math.min(...xs) > 1) {
          out.push({
            kind: "card-row",
            element: describe(tr),
            detail: `values start at ${lefts.map((l) => `${l.cell.getAttribute("data-label")} ${l.left.toFixed(1)}`).join(", ")}`,
          });
        }
      }
    }
  }
  return out;
}
