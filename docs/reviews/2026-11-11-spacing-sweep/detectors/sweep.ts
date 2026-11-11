/**
 * TEMPORARY spacing and overlap sweep (backlog row 245 survey). Not part of the repository: lives only in a throwaway
 * worktree. `sweepChecks` runs inside the page (self-contained) and tags the elements of each finding with
 * `data-sweep-id` so the spec can crop a screenshot around them.
 */
export interface SweepFinding {
  kind: "overlap" | "text-overrun" | "tight-gap" | "misaligned-pair";
  check: boolean;
  a: string;
  b: string;
  detail: string;
  ids: number[];
}

export function sweepChecks(): SweepFinding[] {
  const out: SweepFinding[] = [];
  let nextId = 1;
  const body = document.body;

  function tag(el: Element): number {
    const have = el.getAttribute("data-sweep-id");
    if (have) return Number(have);
    const id = nextId++;
    el.setAttribute("data-sweep-id", String(id));
    return id;
  }

  function locals(el: Element): string[] {
    const cls = typeof el.className === "string" ? el.className : (el.getAttribute("class") ?? "");
    return cls
      .split(/\s+/)
      .filter(Boolean)
      .map((t) => {
        let m = t.match(/-module__[\w-]+?__(.+)$/);
        if (m) return m[1]!;
        m = t.match(/^[A-Za-z0-9-]+_(.+)__[\w-]{5,}$/);
        if (m) return m[1]!;
        return t;
      });
  }
  const hasLocal = (el: Element, re: RegExp) => locals(el).some((l) => re.test(l));

  function describe(el: Element): string {
    const tag = el.tagName.toLowerCase();
    const ui = el.getAttribute("data-ui") ? `[data-ui=${el.getAttribute("data-ui")}]` : "";
    const role = el.getAttribute("role") ? `[role=${el.getAttribute("role")}]` : "";
    const cls = locals(el).slice(0, 2).map((c) => `.${c}`).join("");
    const label =
      el.getAttribute("aria-label") ??
      (el.tagName === "SELECT"
        ? `select:${(el as HTMLSelectElement).selectedOptions[0]?.textContent ?? ""}`
        : el.tagName === "INPUT"
          ? `input:${(el as HTMLInputElement).placeholder || (el as HTMLInputElement).name || (el as HTMLInputElement).type}`
          : (el.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 60));
    return `${tag}${role}${ui}${cls}${label ? ` "${label}"` : ""}`;
  }

  function visible(el: Element): boolean {
    const box = el.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return false;
    const check = (el as Element & { checkVisibility?: (o?: object) => boolean }).checkVisibility;
    if (check && !check.call(el, { checkOpacity: true, checkVisibilityCSS: true })) return false;
    return true;
  }

  function srOnly(el: Element): boolean {
    for (let a: Element | null = el; a && a !== body; a = a.parentElement) {
      if (a.classList.contains("visually-hidden")) return true;
      const r = a.getBoundingClientRect();
      const st = getComputedStyle(a);
      if ((r.width <= 1 || r.height <= 1) && st.overflow !== "visible") return true;
      if (st.clip && st.clip !== "auto" && st.position === "absolute") return true;
    }
    return false;
  }

  const LAYER_ROLES = new Set(["dialog", "alertdialog", "menu", "listbox", "tooltip"]);
  function layerRoot(el: Element): Element {
    for (let a: Element | null = el; a && a !== body; a = a.parentElement) {
      const role = a.getAttribute("role");
      if ((role && LAYER_ROLES.has(role)) || a.tagName === "DIALOG" || a.hasAttribute("popover")) return a;
      const p = getComputedStyle(a).position;
      if (p === "fixed" || p === "sticky" || p === "absolute") return a;
    }
    return body;
  }

  type R = { left: number; top: number; right: number; bottom: number };
  const rectOf = (d: DOMRect): R => ({ left: d.left, top: d.top, right: d.right, bottom: d.bottom });
  const w = (r: R) => r.right - r.left;
  const h = (r: R) => r.bottom - r.top;
  function inter(a: R, b: R): R | null {
    const r = { left: Math.max(a.left, b.left), top: Math.max(a.top, b.top), right: Math.min(a.right, b.right), bottom: Math.min(a.bottom, b.bottom) };
    return r.right > r.left && r.bottom > r.top ? r : null;
  }

  /** The element's box cut by every clipping ancestor; null when nothing of it shows. */
  function shownRect(el: Element): R | null {
    let r: R | null = rectOf(el.getBoundingClientRect());
    for (let a = el.parentElement; a && a !== document.documentElement && r; a = a.parentElement) {
      const st = getComputedStyle(a);
      if (st.overflowX !== "visible" || st.overflowY !== "visible") r = inter(r, rectOf(a.getBoundingClientRect()));
      if (st.position === "fixed") break;
    }
    if (!r || w(r) < 1 || h(r) < 1) return null;
    return r;
  }

  const clipCache = new Map<Element, R | null | "none">();
  /** The box that clips content drawn inside `el` (el itself and its ancestors with overflow other than visible). */
  function clipFor(el: Element): R | null | "none" {
    if (clipCache.has(el)) return clipCache.get(el)!;
    let r: R | null | "none" = "none";
    for (let a: Element | null = el; a && a !== document.documentElement; a = a.parentElement) {
      const st = getComputedStyle(a);
      if (st.overflowX !== "visible" || st.overflowY !== "visible") {
        const b = rectOf(a.getBoundingClientRect());
        r = r === "none" ? b : r ? inter(r, b) : null;
        if (!r) break;
      }
      if (st.position === "fixed") break;
    }
    clipCache.set(el, r);
    return r;
  }

  /** Line rects of the element's own text (and inline svgs), trimmed of spaces; skips absolutely placed bits. */
  function textRects(el: Element, stopAtControls = false): R[] {
    const rects: R[] = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let n: Node | null = walker.currentNode;
    while ((n = walker.nextNode())) {
      if (n.nodeType === Node.ELEMENT_NODE) {
        const e = n as Element;
        if (e.tagName === "svg" && visible(e)) {
          let skip = false;
          for (let a: Element | null = e; a && a !== el; a = a.parentElement) {
            const p = getComputedStyle(a).position;
            if (p === "absolute" || p === "fixed") skip = true;
          }
          const clip = clipFor(e);
          const r = clip === "none" ? rectOf(e.getBoundingClientRect()) : clip ? inter(rectOf(e.getBoundingClientRect()), clip) : null;
          if (!skip && r) rects.push(r);
        }
        continue;
      }
      const t = n as Text;
      const text = t.data;
      const start = text.search(/\S/);
      if (start < 0) continue;
      const end = text.length - (text.match(/\s*$/)?.[0].length ?? 0);
      const parent = t.parentElement;
      if (!parent || !visible(parent) || srOnly(parent)) continue;
      let skip = false;
      for (let a: Element | null = parent; a && a !== el; a = a.parentElement) {
        const st = getComputedStyle(a);
        if (st.position === "absolute" || st.position === "fixed") skip = true;
        if (stopAtControls && a !== el && (a.matches("input,select,textarea,button,[role=combobox]") || a.getAttribute("role") === "radiogroup")) skip = true;
        if (a.tagName === "svg") skip = true;
      }
      if (skip) continue;
      if (parent.closest("svg")) continue;
      const range = document.createRange();
      range.setStart(t, start);
      range.setEnd(t, end);
      const clip = clipFor(parent);
      if (clip === null) continue;
      for (const r0 of Array.from(range.getClientRects())) {
        if (r0.width <= 0.5 || r0.height <= 0.5) continue;
        const r = clip === "none" ? rectOf(r0) : inter(rectOf(r0), clip);
        if (r && w(r) > 0.5 && h(r) > 0.5) rects.push(r);
      }
    }
    return rects;
  }

  function union(rs: R[]): R | null {
    if (!rs.length) return null;
    return rs.reduce((u, r) => ({ left: Math.min(u.left, r.left), top: Math.min(u.top, r.top), right: Math.max(u.right, r.right), bottom: Math.max(u.bottom, r.bottom) }));
  }

  function decoratedBox(el: Element): boolean {
    const st = getComputedStyle(el);
    return (
      (parseFloat(st.borderLeftWidth) > 0 && st.borderLeftStyle !== "none") ||
      (st.backgroundColor !== "rgba(0, 0, 0, 0)" && st.backgroundColor !== "transparent")
    );
  }

  const all = Array.from(body.querySelectorAll("*")).filter((el) => !el.closest("[data-sweep-skip]"));

  // ---------------------------------------------------------------- candidates
  const BUTTONISH = "button,[role=button],a[data-ui=button],[data-ui=button],[role=tab],[role=radio],[role=switch]";
  const isButtonish = (el: Element) => el.matches(BUTTONISH) && !(el.tagName === "INPUT");
  const isField = (el: Element) =>
    (el.tagName === "INPUT" && !["hidden", "checkbox", "radio"].includes((el as HTMLInputElement).type)) ||
    el.tagName === "SELECT" ||
    el.tagName === "TEXTAREA" ||
    el.getAttribute("role") === "combobox";
  const isCheckInput = (el: Element) => el.tagName === "INPUT" && ["checkbox", "radio"].includes((el as HTMLInputElement).type);
  const isBadge = (el: Element) => hasLocal(el, /^(badge|badge-.+|chip|chipOn|filterChip|pill|tag)$/i) || el.getAttribute("data-ui") === "badge";
  const describedIds = new Set<string>();
  for (const el of all) for (const id of (el.getAttribute("aria-describedby") ?? "").split(/\s+/)) if (id) describedIds.add(id);
  const CONTROL_SEL = "input:not([type=hidden]),select,textarea,[role=combobox],[role=radiogroup]";
  const isHint = (el: Element) =>
    hasLocal(el, /^(hint|error|help|fieldHint|note)$/) ||
    (!!el.id && describedIds.has(el.id) && !el.matches(BUTTONISH)) ||
    (el.classList.contains("muted") && !el.querySelector(CONTROL_SEL) && !!el.parentElement?.querySelector(CONTROL_SEL) && !el.closest("td,th"));
  const isLabel = (el: Element) => el.tagName === "LABEL" || el.tagName === "LEGEND";
  const isHeading = (el: Element) => /^H[1-4]$/.test(el.tagName);

  interface Cand {
    el: Element;
    kind: "box" | "text";
    rects: R[];
    box: R;
    layer: Element;
    role: string;
  }
  const cands: Cand[] = [];
  for (const el of all) {
    if (!visible(el) || srOnly(el)) continue;
    let role = "";
    let kind: "box" | "text" = "box";
    if (isButtonish(el)) role = "button";
    else if (isField(el)) role = "field";
    else if (isCheckInput(el)) role = "check";
    else if (isBadge(el)) role = "badge";
    else if (isHint(el)) {
      role = "hint";
      kind = "text";
    } else if (isLabel(el)) {
      role = "label";
      kind = "text";
    } else if (isHeading(el)) {
      role = "heading";
      kind = "text";
    } else continue;
    // a button inside a combobox wrapper etc. is still a button; a badge inside a button is skipped by containment
    const box = shownRect(el);
    if (!box) continue;
    let rects: R[];
    if (kind === "text") {
      rects = textRects(el, true).map((r) => inter(r, box)).filter((r): r is R => !!r && w(r) > 0.5 && h(r) > 0.5);
      if (!rects.length) continue;
    } else rects = [box];
    cands.push({ el, kind, rects, box: union(rects)!, layer: layerRoot(el), role });
  }

  function related(a: Element, b: Element): boolean {
    if (a.contains(b) || b.contains(a)) return true;
    // a label and its own control
    if (a.tagName === "LABEL" && (a as HTMLLabelElement).control === b) return true;
    if (b.tagName === "LABEL" && (b as HTMLLabelElement).control === a) return true;
    return false;
  }

  const seen = new Set<string>();
  function pairKey(k: string, a: Element, b: Element) {
    const ia = tag(a);
    const ib = tag(b);
    return `${k}:${Math.min(ia, ib)}:${Math.max(ia, ib)}`;
  }

  // ---------------------------------------------------------------- overlap
  const sorted = [...cands].sort((x, y) => x.box.top - y.box.top);
  for (let i = 0; i < sorted.length; i++) {
    const A = sorted[i]!;
    for (let j = i + 1; j < sorted.length; j++) {
      const B = sorted[j]!;
      if (B.box.top >= A.box.bottom) break;
      if (A.layer !== B.layer) continue;
      if (!inter(A.box, B.box)) continue;
      if (related(A.el, B.el)) continue;
      // two segment / tab / joined buttons sharing a border
      let hit: R | null = null;
      for (const ra of A.rects) {
        for (const rb of B.rects) {
          const r = inter(ra, rb);
          if (r && w(r) > 2 && h(r) > 2) {
            hit = r;
            break;
          }
        }
        if (hit) break;
      }
      if (!hit) continue;
      const key = pairKey("overlap", A.el, B.el);
      if (seen.has(key)) continue;
      seen.add(key);
      // an element painted over another that is a direct positioned child of a common wrapper (an input's icon) is likelier intended
      const check = (A.role === "heading" || B.role === "heading") || (A.role === "label" && B.role === "label");
      out.push({
        kind: "overlap",
        check,
        a: describe(A.el),
        b: describe(B.el),
        detail: `${A.role} and ${B.role} overlap by ${Math.round(w(hit))}×${Math.round(h(hit))} px`,
        ids: [tag(A.el), tag(B.el)],
      });
    }
  }

  // table cells: one cell's content drawn over another's in the same row
  for (const tr of Array.from(body.querySelectorAll("tr"))) {
    if (!visible(tr)) continue;
    const cells = Array.from(tr.children).filter((c) => (c.tagName === "TD" || c.tagName === "TH") && visible(c) && !srOnly(c));
    const content = cells.map((c) => textRects(c).concat(
      Array.from(c.querySelectorAll("button,input,select,textarea,[data-ui=button],img")).filter((e) => visible(e) && !srOnly(e) && layerRoot(e) === layerRoot(c)).map((e) => rectOf(e.getBoundingClientRect())),
    ));
    for (let i = 0; i < cells.length; i++) {
      const ci = rectOf(cells[i]!.getBoundingClientRect());
      // content spilling out of its own cell with overflow visible
      const ui = union(content[i]!);
      if (ui && (ui.right > ci.right + 2 || ui.left < ci.left - 2)) {
        out.push({
          kind: "text-overrun",
          check: true,
          a: describe(cells[i]!),
          b: "",
          detail: `cell content spills ${Math.round(Math.max(ui.right - ci.right, ci.left - ui.left))} px past its cell`,
          ids: [tag(cells[i]!)],
        });
      }
      for (let j = i + 1; j < cells.length; j++) {
        let hit: R | null = null;
        for (const ra of content[i]!) for (const rb of content[j]!) {
          const r = inter(ra, rb);
          if (r && w(r) > 2 && h(r) > 2) hit = r;
        }
        if (hit) {
          out.push({
            kind: "overlap",
            check: false,
            a: describe(cells[i]!),
            b: describe(cells[j]!),
            detail: `table cell contents overlap by ${Math.round(w(hit))}×${Math.round(h(hit))} px`,
            ids: [tag(cells[i]!), tag(cells[j]!)],
          });
        }
      }
    }
  }

  // ---------------------------------------------------------------- text-overrun
  for (const el of all) {
    if (!visible(el) || srOnly(el)) continue;
    let what = "";
    if (el.matches("[role=radio]") && el.closest("[role=radiogroup]")) what = "segment";
    else if (el.matches("[role=tab]")) what = "tab";
    else if (isBadge(el)) what = "badge";
    else if (el.matches("button,[data-ui=button],a[data-ui=button],[role=button]")) what = "button";
    else if (el.tagName === "SELECT") what = "select";
    else continue;
    const st = getComputedStyle(el);
    const bb = rectOf(el.getBoundingClientRect());
    const bl = parseFloat(st.borderLeftWidth) || 0;
    const br = parseFloat(st.borderRightWidth) || 0;
    const bt = parseFloat(st.borderTopWidth) || 0;
    const bbm = parseFloat(st.borderBottomWidth) || 0;
    const pl = parseFloat(st.paddingLeft) || 0;
    const pr = parseFloat(st.paddingRight) || 0;
    const pad: R = { left: bb.left + bl, right: bb.right - br, top: bb.top + bt, bottom: bb.bottom - bbm };
    const content: R = { left: pad.left + pl, right: pad.right - pr, top: pad.top + (parseFloat(st.paddingTop) || 0), bottom: pad.bottom - (parseFloat(st.paddingBottom) || 0) };
    if (what === "select") {
      const sel = el as HTMLSelectElement;
      const text = sel.selectedOptions[0]?.textContent?.trim() ?? "";
      if (!text) continue;
      const ctx = document.createElement("canvas").getContext("2d")!;
      ctx.font = `${st.fontStyle} ${st.fontWeight} ${st.fontSize} ${st.fontFamily}`;
      const tw = ctx.measureText(text).width;
      const room = w(content);
      if (tw > room + 1) {
        out.push({ kind: "text-overrun", check: true, a: describe(el), b: "", detail: `select's chosen text "${text.slice(0, 40)}" is ${Math.round(tw)} px, room ${Math.round(room)} px (cut off by the arrow area)`, ids: [tag(el)] });
      }
      continue;
    }
    if (st.overflowX !== "visible" && st.textOverflow === "ellipsis") continue;
    if (st.overflowX !== "visible") continue; // the clipped check's job
    // text truncated with ellipsis inside the element
    let truncated = false;
    for (const d of Array.from(el.querySelectorAll("*"))) {
      const ds = getComputedStyle(d);
      if (ds.textOverflow === "ellipsis" && ds.overflowX !== "visible") truncated = true;
    }
    if (truncated) continue;
    const rects = textRects(el);
    const u = union(rects);
    if (!u) continue;
    const roomL = u.left - pad.left;
    const roomR = pad.right - u.right;
    const minRoom = Math.min(roomL, roomR);
    const hasPad = pl >= 4 || pr >= 4;
    const vOut = u.top < pad.top - 1 || u.bottom > pad.bottom + 1;
    if (!hasPad) {
      if (minRoom < -1) out.push({ kind: "text-overrun", check: false, a: describe(el), b: "", detail: `${what} text runs ${Math.round(-minRoom)} px outside its box`, ids: [tag(el)] });
      continue;
    }
    if (minRoom < 2) {
      out.push({
        kind: "text-overrun",
        check: false,
        a: describe(el),
        b: "",
        detail: minRoom < 0 ? `${what} text runs ${Math.round(-minRoom)} px past its ${roomR < roomL ? "right" : "left"} edge` : `${what} text touches its ${roomR < roomL ? "right" : "left"} edge (${minRoom.toFixed(1)} px of ${Math.round(roomR < roomL ? pr : pl)} px padding left)`,
        ids: [tag(el)],
      });
    } else if (u.right > content.right + 2 || u.left < content.left - 2) {
      out.push({
        kind: "text-overrun",
        check: true,
        a: describe(el),
        b: "",
        detail: `${what} text eats into its padding (${Math.round(roomL)} px left, ${Math.round(roomR)} px right of ${Math.round(pl)}/${Math.round(pr)} px)`,
        ids: [tag(el)],
      });
    } else if (vOut && what !== "button") {
      out.push({ kind: "text-overrun", check: true, a: describe(el), b: "", detail: `${what} text runs outside its box vertically`, ids: [tag(el)] });
    } else {
      // the option is wider than its group: the group's frame (switch, chip group, toolbar box) is the edge the eye sees
      let group: Element | null = null;
      let p2: Element | null = el.parentElement;
      for (let k = 0; k < 2 && p2 && p2 !== body; k++, p2 = p2.parentElement) {
        const role = p2.getAttribute("role") ?? "";
        const gs = getComputedStyle(p2);
        if (gs.overflowX !== "visible") break;
        if (["radiogroup", "group", "toolbar"].includes(role) || decoratedBox(p2)) {
          group = p2;
          break;
        }
      }
      if (group) {
        const gs = getComputedStyle(group);
        const gr = rectOf(group.getBoundingClientRect());
        const gpad: R = { left: gr.left + (parseFloat(gs.borderLeftWidth) || 0), right: gr.right - (parseFloat(gs.borderRightWidth) || 0), top: gr.top, bottom: gr.bottom };
        const past = Math.max(bb.right - gpad.right, gpad.left - bb.left);
        if (past > 1) {
          const gRoom = Math.min(u.left - gpad.left, gpad.right - u.right);
          out.push({
            kind: "text-overrun",
            check: false,
            a: describe(el),
            b: describe(group),
            detail: `${what} is ${Math.round(past)} px wider than its group's frame; its text sits ${gRoom.toFixed(1)} px from the frame's edge (own padding ${Math.round(Math.max(pl, pr))} px)`,
            ids: [tag(el), tag(group)],
          });
        }
      }
    }
  }

  // ---------------------------------------------------------------- tight-gap (same line)
  const WIDGET_ROOTS = "[data-ui=office-picker],[data-ui=user-picker],[data-ui=list-search],[role=radiogroup]";
  interface Unit {
    el: Element;
    box: R;
    layer: Element;
  }
  const units: Unit[] = [];
  const unitEls = new Set<Element>();
  function addUnit(el: Element) {
    if (unitEls.has(el)) return;
    if (!visible(el) || srOnly(el)) return;
    const box = shownRect(el);
    if (!box || w(box) < 4 || h(box) < 4) return;
    unitEls.add(el);
    // the unit's visual extent: its options may run past its own box
    let ext = box;
    for (const d of Array.from(el.querySelectorAll("button,[role=radio],input,select"))) {
      if (!visible(d) || srOnly(d)) continue;
      const r = rectOf(d.getBoundingClientRect());
      ext = { left: Math.min(ext.left, r.left), top: Math.min(ext.top, r.top), right: Math.max(ext.right, r.right), bottom: Math.max(ext.bottom, r.bottom) };
    }
    units.push({ el, box: ext, layer: layerRoot(el) });
  }
  for (const el of all) {
    if (el.matches(WIDGET_ROOTS)) {
      if (el.parentElement?.closest(WIDGET_ROOTS)) continue;
      addUnit(el);
      continue;
    }
    if (el.closest(WIDGET_ROOTS)) continue;
    if (el.matches("input[type=checkbox],input[type=radio]")) {
      // the check unit: the kit's check wrapper or the wrapping label
      const wrap = el.closest("label") ?? (el.parentElement && el.parentElement.querySelector("label") ? el.parentElement : null);
      if (wrap) {
        // a label wrapper that is a whole table cell or a big block is not a unit
        addUnit(wrap);
      }
      continue;
    }
    if (el.matches("[role=tab]") || el.closest("[role=tablist]")) continue;
    if (el.matches("button,[data-ui=button],a[data-ui=button],[role=switch]") || isField(el)) {
      if (el.closest("label")?.querySelector("input[type=checkbox],input[type=radio]")) continue;
      addUnit(el);
    }
  }
  function decorated(el: Element): boolean {
    const st = getComputedStyle(el);
    return (
      (parseFloat(st.borderLeftWidth) > 0 && st.borderLeftStyle !== "none") ||
      st.boxShadow !== "none" ||
      (st.backgroundColor !== "rgba(0, 0, 0, 0)" && st.backgroundColor !== "transparent")
    );
  }
  function composite(a: Element, b: Element, ua: R): boolean {
    // a decorated common ancestor hugging both: one composite control (an input group)
    for (let c = a.parentElement; c && c !== body; c = c.parentElement) {
      if (!c.contains(b)) continue;
      const cr = rectOf(c.getBoundingClientRect());
      const bb = rectOf(b.getBoundingClientRect());
      const u = { left: Math.min(ua.left, bb.left), top: Math.min(ua.top, bb.top), right: Math.max(ua.right, bb.right), bottom: Math.max(ua.bottom, bb.bottom) };
      if (u.left - cr.left <= 6 && cr.right - u.right <= 6 && u.top - cr.top <= 6 && cr.bottom - u.bottom <= 6 && decorated(c)) return true;
      return false;
    }
    return false;
  }
  for (const A of units) {
    let best: Unit | null = null;
    let bestGap = Infinity;
    for (const B of units) {
      if (A === B || A.layer !== B.layer) continue;
      if (A.el.contains(B.el) || B.el.contains(A.el)) continue;
      const vo = Math.min(A.box.bottom, B.box.bottom) - Math.max(A.box.top, B.box.top);
      if (vo < 0.5 * Math.min(h(A.box), h(B.box))) continue;
      if (B.box.left < A.box.left + 2) continue;
      const gap = B.box.left - A.box.right;
      if (gap < bestGap) {
        bestGap = gap;
        best = B;
      }
    }
    if (!best || bestGap >= 6) continue;
    // different table cells are spaced by the cell padding
    const ca = A.el.closest("td,th");
    const cb = best.el.closest("td,th");
    if (ca && cb && ca !== cb) continue;
    if (composite(A.el, best.el, A.box)) continue;
    const key = pairKey("gap", A.el, best.el);
    if (seen.has(key)) continue;
    seen.add(key);
    const both = (e: Element) => e.matches("button,[data-ui=button],a[data-ui=button]");
    const joined = bestGap <= 0.5 && bestGap > -2 && both(A.el) && both(best.el) && A.el.parentElement === best.el.parentElement;
    const dup = out.some((f) => f.kind === "overlap" && f.ids.length === 2 && (() => {
      const x = document.querySelector(`[data-sweep-id="${f.ids[0]}"]`);
      const y = document.querySelector(`[data-sweep-id="${f.ids[1]}"]`);
      if (!x || !y) return false;
      const inA = (e: Element) => A.el.contains(e) || e.contains(A.el);
      const inB = (e: Element) => best!.el.contains(e) || e.contains(best!.el);
      return (inA(x) && inB(y)) || (inA(y) && inB(x));
    })());
    if (bestGap <= -3 && dup) continue;
    if (bestGap <= -3) {
      out.push({ kind: "overlap", check: false, a: describe(A.el), b: describe(best.el), detail: `controls on one line overlap by ${Math.round(-bestGap)} px`, ids: [tag(A.el), tag(best.el)] });
    } else {
      out.push({
        kind: "tight-gap",
        check: joined,
        a: describe(A.el),
        b: describe(best.el),
        detail: `${bestGap.toFixed(1)} px between neighbouring controls on one line${joined ? " (looks like a joined button group)" : ""}`,
        ids: [tag(A.el), tag(best.el)],
      });
    }
  }

  // ---------------------------------------------------------------- tight-gap (hint above the next field)
  const fieldWrap = (el: Element) => el.closest("[data-ui=segmented-field]") ?? el.parentElement?.closest("div") ?? null;
  for (const H of cands) {
    if (H.role !== "hint") continue;
    const own = H.el.parentElement;
    const wrapH = fieldWrap(H.el);
    let best: { el: Element; top: number } | null = null;
    for (const C of cands) {
      if (C === H || C.layer !== H.layer) continue;
      if (C.role !== "label" && C.role !== "field" && C.role !== "check" && C.role !== "button" && C.role !== "hint") continue;
      if (C.el.contains(H.el) || H.el.contains(C.el)) continue;
      if (own && own.contains(C.el)) continue; // the hint's own field
      if (wrapH && wrapH.contains(C.el)) continue;
      if (C.box.top < H.box.top + h(H.box) * 0.5) continue;
      const ho = Math.min(H.box.right, C.box.right) - Math.max(H.box.left, C.box.left);
      if (ho <= 4) continue;
      if (!best || C.box.top < best.top) best = { el: C.el, top: C.box.top };
    }
    if (!best) continue;
    const gap = best.top - H.box.bottom;
    if (gap < 4 && gap > -3) {
      const key = pairKey("vgap", H.el, best.el);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ kind: "tight-gap", check: false, a: describe(H.el), b: describe(best.el), detail: `${gap.toFixed(1)} px between a hint and the next field below`, ids: [tag(H.el), tag(best.el)] });
    }
  }

  // ---------------------------------------------------------------- tight-gap / overlap between texts of different fields on one line
  const fieldOf = (el: Element) => el.closest("[data-ui=segmented-field]") ?? el.parentElement;
  const texts = cands.filter((c) => c.role === "hint" || c.role === "label");
  for (const A of texts) {
    for (const B of texts) {
      if (A === B || A.layer !== B.layer || related(A.el, B.el)) continue;
      const fa = fieldOf(A.el);
      const fb = fieldOf(B.el);
      if (fa && fb && (fa === fb || fa.contains(B.el) || fb.contains(A.el))) continue;
      let worst: number | null = null;
      for (const ra of A.rects) for (const rb of B.rects) {
        const vo = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
        if (vo < 0.5 * Math.min(h(ra), h(rb))) continue;
        if (rb.left < ra.left) continue;
        const gap = rb.left - ra.right;
        if (gap < 6 && gap > -40 && (worst === null || gap < worst)) worst = gap;
      }
      if (worst === null) continue;
      const key = pairKey("tgap", A.el, B.el);
      if (seen.has(key) || seen.has(pairKey("overlap", A.el, B.el))) continue;
      seen.add(key);
      out.push({
        kind: worst <= -2 ? "overlap" : "tight-gap",
        check: A.role === "label" && B.role === "label",
        a: describe(A.el),
        b: describe(B.el),
        detail: worst <= -2 ? `texts of two fields run into each other by ${Math.round(-worst)} px` : `${worst.toFixed(1)} px between texts of two neighbouring fields (${A.role} / ${B.role}) on one line`,
        ids: [tag(A.el), tag(B.el)],
      });
    }
  }

  // ---------------------------------------------------------------- misaligned-pair
  const isBtn = (e: Element) => e.matches("button,[data-ui=button],a[data-ui=button]") && !e.closest("[role=radiogroup],[role=tablist],td,th");
  const asButton = (child: Element): Element | null => {
    if (isBtn(child)) return child;
    const inner = Array.from(child.children);
    if (inner.length === 1 && isBtn(inner[0]!)) return inner[0]!;
    return null;
  };
  const groupsDone = new Set<Element>();
  for (const p of all) {
    if (!visible(p) || groupsDone.has(p)) continue;
    const st = getComputedStyle(p);
    if (!(st.display.includes("flex") || st.display.includes("grid"))) continue;
    if (st.display.includes("flex") && st.flexDirection.startsWith("column")) continue;
    const kids = Array.from(p.children).filter((c) => visible(c) && !srOnly(c) && getComputedStyle(c).position !== "absolute");
    // runs of consecutive button children
    let run: Element[] = [];
    const runs: Element[][] = [];
    for (const k of kids) {
      const b = asButton(k);
      if (b) run.push(k);
      else {
        if (run.length >= 2) runs.push(run);
        run = [];
      }
    }
    if (run.length >= 2) runs.push(run);
    for (const r of runs) {
      const boxes = r.map((k) => rectOf(k.getBoundingClientRect()));
      const lines: R[][] = [];
      for (const b of boxes) {
        const line = lines.find((l) => Math.min(l[0]!.bottom, b.bottom) - Math.max(l[0]!.top, b.top) > 0.5 * Math.min(h(l[0]!), h(b)));
        if (line) line.push(b);
        else lines.push([b]);
      }
      if (lines.length < 2) continue;
      const pr = rectOf(p.getBoundingClientRect());
      const full = boxes.every((b) => w(b) >= 0.85 * w(pr));
      if (full) continue;
      if (lines.length === boxes.length && boxes.every((b) => Math.abs(b.left - boxes[0]!.left) < 2) && boxes.length > 2) continue; // a deliberate stack
      out.push({
        kind: "misaligned-pair",
        check: document.documentElement.clientWidth < 700 || st.display.includes("grid"),
        a: describe(r[0]!),
        b: r.slice(1).map((k) => describe(k)).join(" | "),
        detail: `${boxes.length} buttons of one group fall on ${lines.length} lines (${lines.map((l) => l.length).join("+")}) in a ${st.display} parent ${describe(p).split(" ")[0]}`,
        ids: r.map((k) => tag(k)),
      });
    }
  }

  return out;
}
