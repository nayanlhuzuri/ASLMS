"use client";

/**
 * The Office Picker (design portal-ui-polish-2, decision 28), the one way to choose an office: the ARIA combobox
 * pattern over the office tree. The list is indented by depth with each office's code greyed on the right; typing
 * filters by name or code (case ignored), highlights the match and shows the ancestor path under it; "No office
 * matches" when nothing does. The box carries an office icon, the chosen office's code tag (with "+ sub" when the
 * subtree is included and the office has children), a clear button and a chevron, and is one 36 px control. The list
 * opens in a portal under the box (above it when there is no room), mounted inside the nearest dialog so the focus
 * trap holds and no overlay body clips it. Keys: Down opens or moves down, Up moves up, Home and End, Enter chooses,
 * Escape closes keeping the value, Tab closes. The value is the office code, which every API takes.
 *
 * The offices come from `GET /admin/offices/choices?purpose=` (`purpose`) or from the page (`options`, the Reports
 * catalogue). Showing an office is convenience only: every write and filter checks again on the server.
 */
import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { useOfficeChoices } from "@/lib/api/hooks";
import type { OfficeChoice, OfficePurpose } from "@/lib/api/types";
import { T } from "@/lib/messages";

import { CheckField, cx } from "./controls";
import c from "./controls.module.css";
import { Badge } from "./feedback";
import s from "./officePicker.module.css";

const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/** The options shown for a query: the whole tree when empty, else the offices whose name or code holds it. */
export function filterOffices(options: OfficeChoice[], query: string): OfficeChoice[] {
  const q = query.trim().toLowerCase();
  if (!q) return options;
  return options.filter((o) => o.name.toLowerCase().includes(q) || o.code.toLowerCase().includes(q));
}

/** The text with the first occurrence of the query marked. */
function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim().toLowerCase();
  const at = q ? text.toLowerCase().indexOf(q) : -1;
  if (at < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <mark className={s.mark}>{text.slice(at, at + q.length)}</mark>
      {text.slice(at + q.length)}
    </>
  );
}

function OfficeIcon() {
  return (
    <svg className={s.icon} aria-hidden="true" width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 15V4l6-2 6 2v11M1 15h16M7 15v-3h4v3M6 6h1M11 6h1M6 9h1M11 9h1" />
    </svg>
  );
}

export interface OfficePickerProps {
  /** The field label (visually hidden with `hideLabel`; the placeholder then shows it). */
  label: ReactNode;
  hideLabel?: boolean;
  /** Where the offices come from: the server's list for this purpose… */
  purpose?: OfficePurpose;
  /** …or a list given by the page (no call). */
  options?: OfficeChoice[];
  value: string | null;
  onChange: (code: string | null) => void;
  /** Told the whole office when one is chosen (undefined when cleared): the mapping's generic-code rule reads it. */
  onChoose?: (office: OfficeChoice | undefined) => void;
  /** Only these office kinds (for example departments only). */
  kinds?: string[];
  /** The Include Sub-offices checkbox under the box (filters). */
  subtree?: { value: boolean; onChange: (value: boolean) => void };
  /** Inactive offices too, marked "Inactive" (where the purpose allows them). */
  includeInactive?: boolean;
  placeholder?: string;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  disabled?: boolean;
  id?: string;
}

export function OfficePicker({
  label,
  hideLabel,
  purpose,
  options: given,
  value,
  onChange,
  onChoose,
  kinds,
  subtree,
  includeInactive = false,
  placeholder,
  hint,
  error,
  required,
  disabled,
  id,
}: OfficePickerProps) {
  const auto = useId();
  const inputId = id ?? `${auto}-office`;
  const listId = `${auto}-list`;
  const hintId = `${auto}-hint`;
  const errorId = `${auto}-error`;
  const choices = useOfficeChoices(given ? undefined : purpose, includeInactive && purpose !== "audit", !given);
  const all = useMemo(() => {
    const list = given ?? choices.data?.items ?? [];
    return list.filter((o) => (!kinds || kinds.includes(o.kind)) && (includeInactive || o.is_active || purpose === "audit"));
  }, [given, choices.data, kinds, includeInactive, purpose]);
  const minDepth = all.length ? Math.min(...all.map((o) => o.depth)) : 0;
  const chosen = value ? all.find((o) => o.code === value) : undefined;
  const hasChildren = !!chosen && all.some((o) => o.parent_code === chosen.code);

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const shown = useMemo(() => filterOffices(all, query ?? ""), [all, query]);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const right = useRef<HTMLSpanElement>(null);
  const [padRight, setPadRight] = useState<number | undefined>(undefined);
  const [place, setPlace] = useState<CSSProperties>({});
  const [host, setHost] = useState<Element | null>(null);

  // the text in the box: what is being typed, else the chosen office's name, else the code while the list loads
  const text = query ?? (chosen ? chosen.name : (value ?? ""));

  useIsoLayoutEffect(() => {
    const width = right.current?.offsetWidth;
    if (width) setPadRight(width + 8);
  }, [chosen?.code, subtree?.value, hasChildren, value]);

  function position() {
    const el = box.current;
    if (!el || typeof window === "undefined") return;
    const r = el.getBoundingClientRect();
    const room = window.innerHeight - r.bottom;
    const above = room < 240 && r.top > room;
    setPlace({
      left: r.left,
      width: Math.max(r.width, Math.min(300, window.innerWidth - 32)),
      ...(above ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }),
    });
  }

  useEffect(() => {
    if (!open) return;
    position();
    const onMove = () => position();
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !list.current?.parentElement?.contains(t)) {
        setOpen(false);
        setQuery(null);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open || !list.current) return;
    list.current.querySelector<HTMLElement>(`[data-index='${active}']`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, open]);

  function openList() {
    if (disabled) return;
    // inside an overlay the list mounts in the overlay root, so the focus trap holds and no body clips it
    setHost(box.current?.closest("[role='dialog']") ?? document.body);
    const at = chosen ? shown.findIndex((o) => o.code === chosen.code) : 0;
    setActive(Math.max(0, at));
    setOpen(true);
  }

  function close() {
    setOpen(false);
    setQuery(null);
  }

  function choose(o: OfficeChoice) {
    onChange(o.code);
    onChoose?.(o);
    close();
    input.current?.focus();
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    const last = shown.length - 1;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) openList();
        else setActive((a) => Math.min(last, a + 1));
        return;
      case "ArrowUp":
        e.preventDefault();
        if (open) setActive((a) => Math.max(0, a - 1));
        return;
      case "Home":
        if (!open) return;
        e.preventDefault();
        setActive(0);
        return;
      case "End":
        if (!open) return;
        e.preventDefault();
        setActive(Math.max(0, last));
        return;
      case "Enter":
        if (!open) return;
        e.preventDefault();
        if (shown[active]) choose(shown[active]!);
        return;
      case "Escape":
        if (!open) return;
        // the list closes and the value stays; the overlay around does not close
        e.preventDefault();
        e.stopPropagation();
        close();
        return;
      case "Tab":
        if (open) close();
        return;
    }
  }

  const activeId = open && shown[active] ? `${listId}-${active}` : undefined;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;

  const popover = open ? (
    <div className={cx(s.pop, host === document.body && s.popTop)} style={place} data-ui="office-picker-list">
      <ul ref={list} id={listId} role="listbox" aria-label={T.officePicker.listAria} className={s.list}>
        {shown.length === 0 ? (
          <li className={s.none} role="presentation">
            {choices.isPending && !given ? T.officePicker.loadingNote : T.officePicker.noMatch}
          </li>
        ) : (
          shown.map((o, i) => (
            <li
              key={o.code}
              id={`${listId}-${i}`}
              data-index={i}
              role="option"
              aria-selected={o.code === value}
              className={cx(s.option, i === active && s.active)}
              style={{ "--depth": query ? 0 : o.depth - minDepth } as CSSProperties}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(o);
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span className={s.name}>
                <Highlight text={o.name} query={query ?? ""} />
                {query && o.ancestors.length ? <span className={s.path}>{o.ancestors.join(" › ")}</span> : null}
              </span>
              {!o.is_active ? <Badge>{T.officePicker.inactiveBadge}</Badge> : null}
              <span className={s.code}>
                <Highlight text={o.code} query={query ?? ""} />
              </span>
            </li>
          ))
        )}
      </ul>
      <div className={s.foot}>{T.officePicker.footNote}</div>
    </div>
  ) : null;

  return (
    <div className={cx(c.field, s.field)} data-ui="office-picker">
      <label className={cx(c.label, hideLabel && "visually-hidden")} htmlFor={inputId}>
        {label}
      </label>
      <div ref={box} className={cx(s.box, open && s.open)}>
        <OfficeIcon />
        <input
          ref={input}
          id={inputId}
          className={cx(c.input, c.control, s.input)}
          style={padRight ? { paddingRight: padRight } : undefined}
          data-ui="field"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          aria-required={required || undefined}
          autoComplete="off"
          disabled={disabled}
          placeholder={placeholder ?? (hideLabel && typeof label === "string" ? label : T.officePicker.placeholderChoose)}
          value={text}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
            if (!open) openList();
          }}
          onClick={() => (open ? undefined : openList())}
          onKeyDown={onKey}
          onBlur={() => {
            // a click on an option keeps the focus (mousedown prevented); any other blur closes the list
            if (open) close();
          }}
        />
        <span ref={right} className={s.right}>
          {chosen || value ? <span className={s.codeTag}>{chosen?.code ?? value}</span> : null}
          {subtree?.value && hasChildren ? <span className={s.sub}>{T.officePicker.subMarker}</span> : null}
          {value && !disabled ? (
            <button
              type="button"
              className={s.clear}
              aria-label={T.officePicker.clearAria}
              onClick={() => {
                onChange(null);
                onChoose?.(undefined);
                setQuery(null);
                input.current?.focus();
              }}
            >
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="m3 3 8 8M11 3l-8 8" />
              </svg>
            </button>
          ) : null}
          <span className={s.chev} aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="m4 6 4 4 4-4" />
            </svg>
          </span>
        </span>
      </div>
      {subtree ? (
        <CheckField label={T.officePicker.subtreeLabel} checked={subtree.value} onChange={(e) => subtree.onChange(e.target.checked)} />
      ) : null}
      {hint ? (
        <span id={hintId} className={c.hint}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span id={errorId} className={c.error} role="alert">
          {error}
        </span>
      ) : null}
      {popover && host ? createPortal(popover, host) : null}
    </div>
  );
}
