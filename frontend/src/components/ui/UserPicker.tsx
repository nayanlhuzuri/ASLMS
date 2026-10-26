"use client";

/**
 * The User Picker (design office-head-picker, decision 2), the way to choose a person who already has an ASLMS login:
 * the ARIA combobox of the Office Picker over `GET /admin/users?q=&limit=20` (the caller's `users.view` scope; no new
 * endpoint, decision 3). After 2 characters and a 300 ms pause one request; up to 20 options, then "Showing the first
 * 20 — type more to narrow". Each option shows the name with the match marked, the e-mail greyed, and the person's
 * offices (primary first, at most 3, then "+ n more", a Head badge on a head membership), or the No Office Yet / No
 * Active Office badge. Options that cannot be chosen are greyed with their reason and skipped by the keys: sign-in
 * off, the Super Administrator, and whatever the page's `blocked` says. The box is one 36 px control with a person
 * icon, a clear button and a chevron; the chosen person's name is in the box, the e-mail beside it and the offices
 * line under it. The list opens in a portal under the box (above it when there is no room), inside the nearest
 * dialog. Keys: Down, Up, Home, End, Enter chooses, Escape closes keeping the value, Tab closes. Showing a person is
 * convenience only: the server checks every rule again.
 */
import { useQuery } from "@tanstack/react-query";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { apiPage } from "@/lib/api/client";
import { labelOf, useLabels } from "@/lib/api/hooks";
import type { MembershipOut, UserChoice, UserTypeLabel } from "@/lib/api/types";
import { T } from "@/lib/messages";

import { cx } from "./controls";
import c from "./controls.module.css";
import { Badge } from "./feedback";
import s from "./officePicker.module.css";
import u from "./userPicker.module.css";

export const USER_PICKER_LIMIT = 20;
export const USER_PICKER_DEBOUNCE_MS = 300;
const MAX_OFFICES = 3;

/** The value after it has stayed unchanged for `ms`. */
function useDebounced<V>(value: V, ms: number): V {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}

/** The active memberships, primary first. */
export function activeOffices(user: Pick<UserChoice, "memberships">): MembershipOut[] {
  const active = (user.memberships ?? []).filter((m) => m.is_active !== false);
  return [...active.filter((m) => m.is_primary), ...active.filter((m) => !m.is_primary)];
}

/** The reasons every picker greys an option for (decision 2); the page's own come after. */
export function baseBlock(user: UserChoice): string | null {
  if (!user.is_active) return T.userPicker.signInOffNote;
  if (activeOffices(user).some((m) => m.role === "super_admin")) return T.userPicker.superAdminNote;
  return null;
}

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

/** The person's offices as "<code> · <designation> · <type>" (a Head badge on a head), or the no-office badge. */
export function OfficesLine({ user, types }: { user: UserChoice; types: UserTypeLabel[] | undefined }) {
  const offices = activeOffices(user);
  if (offices.length === 0) {
    return <Badge>{user.office === null ? T.userPicker.noOfficeYetBadge : T.userPicker.noActiveOfficeBadge}</Badge>;
  }
  return (
    <span className={u.offices}>
      {offices.slice(0, MAX_OFFICES).map((m) => (
        <span key={m.id} className={u.office} data-office={m.office.code}>
          {[m.office.code, m.designation, labelOf(types, m.role)].filter(Boolean).join(" · ")}
          {m.role === "dept_head" ? (
            <>
              {" "}
              <Badge tone="info">{T.userPicker.headBadge}</Badge>
            </>
          ) : null}
        </span>
      ))}
      {offices.length > MAX_OFFICES ? <span className={u.more}>{T.userPicker.moreNote(offices.length - MAX_OFFICES)}</span> : null}
    </span>
  );
}

function PersonIcon() {
  return (
    <svg className={s.icon} aria-hidden="true" width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="9" cy="6" r="3.5" />
      <path d="M2.5 16c.8-3.2 3.3-5 6.5-5s5.7 1.8 6.5 5" />
    </svg>
  );
}

export interface UserPickerProps {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  disabled?: boolean;
  id?: string;
  value: UserChoice | null;
  onChange: (user: UserChoice | null) => void;
  /** The page's own reason an option cannot be chosen (null: it can). */
  blocked?: (user: UserChoice) => string | null;
  /** Also logins that left their last office (`include_ended=true`; a State-wide caller only). */
  includeWithoutOffice?: boolean;
}

export function UserPicker({
  label,
  hint,
  error,
  required,
  disabled,
  id,
  value,
  onChange,
  blocked,
  includeWithoutOffice = false,
}: UserPickerProps) {
  const auto = useId();
  const inputId = id ?? `${auto}-user`;
  const listId = `${auto}-list`;
  const hintId = `${auto}-hint`;
  const errorId = `${auto}-error`;
  const labels = useLabels();
  const types = labels.data?.user_types;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState<string | null>(null);
  const [active, setActive] = useState(0);
  const typed = (query ?? "").trim();
  const settled = useDebounced(typed, USER_PICKER_DEBOUNCE_MS);
  const enough = settled.length >= 2;
  const people = useQuery({
    queryKey: ["admin", "users", "picker", settled, includeWithoutOffice],
    queryFn: () =>
      apiPage<UserChoice[]>("/admin/users", {
        query: { q: settled, limit: USER_PICKER_LIMIT, include_ended: includeWithoutOffice || undefined },
      }),
    enabled: open && enough,
    staleTime: 30_000,
  });
  const shown = useMemo(() => (enough && typed.length >= 2 ? (people.data?.items ?? []) : []), [enough, typed, people.data]);
  const reasons = useMemo(() => shown.map((p) => baseBlock(p) ?? blocked?.(p) ?? null), [shown, blocked]);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const [place, setPlace] = useState<CSSProperties>({});
  const [host, setHost] = useState<Element | null>(null);

  const text = query ?? value?.full_name ?? "";

  function position() {
    const el = box.current;
    if (!el || typeof window === "undefined") return;
    const r = el.getBoundingClientRect();
    const room = window.innerHeight - r.bottom;
    const above = room < 240 && r.top > room;
    const width = Math.min(Math.max(r.width, 320), window.innerWidth - 32);
    setPlace({
      left: Math.max(16, Math.min(r.left, window.innerWidth - 16 - width)),
      width,
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

  // the first option that can be chosen is active when a new answer arrives (state adjusted while rendering)
  const answerKey = shown.map((p, i) => `${p.id}:${reasons[i] === null ? 1 : 0}`).join(",");
  const [seenKey, setSeenKey] = useState(answerKey);
  if (seenKey !== answerKey) {
    setSeenKey(answerKey);
    const first = reasons.findIndex((r) => r === null);
    setActive(first < 0 ? 0 : first);
  }

  useEffect(() => {
    if (!open || !list.current) return;
    list.current.querySelector<HTMLElement>(`[data-index='${active}']`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, open]);

  function openList() {
    if (disabled) return;
    setHost(box.current?.closest("[role='dialog']") ?? document.body);
    setOpen(true);
  }

  function close() {
    setOpen(false);
    setQuery(null);
  }

  function choose(i: number) {
    const p = shown[i];
    if (!p || reasons[i] !== null) return;
    onChange(p);
    close();
    input.current?.focus();
  }

  /** The next option that can be chosen from `from` in `step` (+1 / -1), or `from` when there is none. */
  function next(from: number, step: number): number {
    for (let i = from + step; i >= 0 && i < shown.length; i += step) if (reasons[i] === null) return i;
    return from;
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (!open) openList();
        else setActive((a) => next(a, 1));
        return;
      case "ArrowUp":
        e.preventDefault();
        if (open) setActive((a) => next(a, -1));
        return;
      case "Home":
        if (!open) return;
        e.preventDefault();
        setActive((a) => {
          const first = next(-1, 1);
          return first < 0 ? a : first;
        });
        return;
      case "End":
        if (!open) return;
        e.preventDefault();
        setActive((a) => {
          const last = next(shown.length, -1);
          return last >= shown.length ? a : last;
        });
        return;
      case "Enter":
        if (!open) return;
        e.preventDefault();
        choose(active);
        return;
      case "Escape":
        if (!open) return;
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
  const total = people.data?.total ?? 0;

  let note: string | null = null;
  if (typed.length < 2) note = T.userPicker.minimumNote;
  else if (!enough || settled !== typed || people.isPending) note = T.userPicker.loadingNote;
  else if (shown.length === 0) note = T.userPicker.noneNote(typed);

  const popover = open ? (
    <div className={cx(s.pop, host === document.body && s.popTop)} style={place} data-ui="user-picker-list">
      <ul ref={list} id={listId} role="listbox" aria-label={T.userPicker.listAria} className={s.list}>
        {note ? (
          <li className={s.none} role="presentation">
            {note}
          </li>
        ) : (
          shown.map((p, i) => {
            const reason = reasons[i];
            return (
              <li
                key={p.id}
                id={`${listId}-${i}`}
                data-index={i}
                role="option"
                aria-selected={p.id === value?.id}
                aria-disabled={reason ? true : undefined}
                aria-label={[`${p.full_name}, ${p.email}`, reason].filter(Boolean).join(" — ")}
                className={cx(s.option, u.option, i === active && !reason && s.active, reason && u.blocked)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  choose(i);
                }}
                onMouseEnter={() => (reason ? undefined : setActive(i))}
              >
                <span className={u.lines}>
                  <span className={u.who}>
                    <span className={u.name}>
                      <Highlight text={p.full_name} query={typed} />
                    </span>
                    <span className={u.email}>
                      <Highlight text={p.email} query={typed} />
                    </span>
                  </span>
                  <OfficesLine user={p} types={types} />
                  {reason ? <span className={u.reason}>{reason}</span> : null}
                </span>
              </li>
            );
          })
        )}
      </ul>
      {!note && total > shown.length ? <div className={s.foot}>{T.userPicker.firstNote}</div> : null}
    </div>
  ) : null;

  return (
    <div className={cx(c.field, s.field, u.field)} data-ui="user-picker">
      <label className={c.label} htmlFor={inputId}>
        {label}
      </label>
      <div ref={box} className={cx(s.box, open && s.open)}>
        <PersonIcon />
        <input
          ref={input}
          id={inputId}
          className={cx(c.input, c.control, s.input)}
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
          placeholder={T.userPicker.placeholder}
          value={text}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!open) openList();
          }}
          onClick={() => (open ? undefined : openList())}
          onKeyDown={onKey}
          onBlur={() => {
            if (open) close();
          }}
        />
        <span className={s.right}>
          {value && query === null ? <span className={s.codeTag}>{value.email}</span> : null}
          {value && !disabled ? (
            <button
              type="button"
              className={s.clear}
              aria-label={T.userPicker.clearAria}
              onClick={() => {
                onChange(null);
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
      {value ? (
        <span className={u.chosen} data-ui="user-picker-chosen">
          <OfficesLine user={value} types={types} />
        </span>
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
