"use client";

/**
 * Overlays of the UI kit (design portal-ui-redesign, decisions 13, 16, 17 and 20): the dialog (with the confirm
 * dialog on it), the large modal, the side panel and the dropdown menu. `Dialog`, `Modal` and `SidePanel` share one
 * behaviour: focus moves in and is trapped, Escape closes, the focus returns on close, `aria-modal`, the page does not
 * scroll behind, and they ease in and out (instantly under reduced motion). Phones get them full screen. While one
 * eases out after closing it is inert (`inert`, no pointer events), so a second click cannot submit twice (review of
 * round 1, fixed in round 2).
 */
import Link from "next/link";
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";

import { T, type ErrorTexts } from "@/lib/messages";

import { Button, cx } from "./controls";
import { ErrorBanner } from "./feedback";
import { DURATION, usePresence } from "./motion";
import s from "./overlays.module.css";

const FOCUSABLE =
  "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), iframe, [tabindex]:not([tabindex='-1'])";

const FIELD = "input:not([type='hidden']):not([disabled]), select:not([disabled]), textarea:not([disabled])";
const CONTROL = `${FIELD}, a[href], button:not([disabled]), [tabindex]:not([tabindex='-1'])`;

/**
 * Where an overlay's focus goes first (design portal-ui-polish, decision 3): the first field of the body, else the
 * body's first enabled control, else the footer's first control, else the first control anywhere (the header's
 * Close only when it is the only control), else the overlay itself. The body and footer are marked
 * `data-overlay-part`; an overlay without the marks (the phone drawer) is searched as a whole. A control marked
 * `data-autofocus` comes first (design session-timeout, decision 17: Stay Signed In, not Sign Out, takes the focus).
 */
export function firstFocus(root: HTMLElement): HTMLElement {
  const preferred = root.querySelector<HTMLElement>("[data-autofocus]:not([disabled])");
  if (preferred) return preferred;
  const body = root.querySelector<HTMLElement>("[data-overlay-part='body']");
  const foot = root.querySelector<HTMLElement>("[data-overlay-part='footer']");
  const scope = body ?? (foot ? null : root);
  return (
    scope?.querySelector<HTMLElement>(FIELD) ??
    scope?.querySelector<HTMLElement>(CONTROL) ??
    foot?.querySelector<HTMLElement>(CONTROL) ??
    root.querySelector<HTMLElement>(CONTROL) ??
    root
  );
}

/** The open overlays, innermost last: only the innermost one answers Escape and Tab. */
const stack: symbol[] = [];
let scrollLocks = 0;
let savedOverflow = "";

function lockScroll(): () => void {
  if (typeof document === "undefined") return () => {};
  if (scrollLocks === 0) {
    savedOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  scrollLocks += 1;
  return () => {
    scrollLocks -= 1;
    if (scrollLocks === 0) document.body.style.overflow = savedOverflow;
  };
}

/**
 * The shared overlay behaviour on `ref` while `active`: `firstFocus` takes the focus, Tab stays inside, Escape calls `onClose`, the page is scroll-locked, and the focus returns where it was.
 */
export function useOverlay(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  onClose: () => void,
  { lock = true }: { lock?: boolean } = {},
) {
  // the latest onClose, so a parent's new function on each render does not move the focus back to the start
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    if (!active) return;
    const id = Symbol("overlay");
    stack.push(id);
    const previous = document.activeElement as HTMLElement | null;
    if (ref.current) firstFocus(ref.current).focus();
    const unlock = lock ? lockScroll() : () => {};
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !ref.current) return;
      // keep the focus inside (WCAG 2.1: a modal dialog traps focus)
      const focusable = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) {
        e.preventDefault();
        return;
      }
      const firstEl = focusable[0]!;
      const lastEl = focusable[focusable.length - 1]!;
      const inside = ref.current.contains(document.activeElement);
      if (e.shiftKey && (document.activeElement === firstEl || !inside)) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && (document.activeElement === lastEl || !inside)) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      const at = stack.indexOf(id);
      if (at >= 0) stack.splice(at, 1);
      unlock();
      previous?.focus?.();
    };
  }, [active, lock, ref]);
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <Button variant="ghost" className={s.close} onClick={onClose} aria-label={T.close}>
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M6 6l12 12M18 6 6 18" />
      </svg>
    </Button>
  );
}

/**
 * The dialog on the Action dialog template (decision 25): 560 px wide (720 px with `wide`, the note composer), a header
 * with the title and an optional subtitle (the case number) and more under it (a stepper), a scrolling body, and an
 * optional footer fixed at the bottom; full screen on phones. It eases in and out.
 */
export function Dialog({
  open,
  title,
  subtitle,
  head,
  onClose,
  children,
  footer,
  wide,
}: {
  open: boolean;
  title: string;
  /** Under the title: the case number on a case's workflow dialogs. */
  subtitle?: ReactNode;
  /** More in the header, under the title (the stepper of a stepped dialog). */
  head?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** The footer fixed at the bottom: Cancel or Back on the left, one primary on the right. */
  footer?: ReactNode;
  /** 720 px instead of 560 px (the note composer). */
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const { mounted, closing } = usePresence(open, DURATION.med);
  useOverlay(ref, open, onClose);
  if (!mounted) return null;
  return (
    <div className={cx(s.overlay, s.center, closing && s.closing)} inert={closing || undefined} data-closing={closing || undefined}>
      <div
        ref={ref}
        className={cx(s.dialog, wide && s.wide, closing && s.closing)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className={s.dialogHead}>
          <div className={s.dialogTitle}>
            <h2 id={titleId}>{title}</h2>
            {subtitle ? <p className={cx(s.dialogSub, "cno")}>{subtitle}</p> : null}
            {head}
          </div>
          <CloseButton onClose={onClose} />
        </div>
        <div className={s.dialogBody} data-overlay-part="body">
          {children}
        </div>
        {footer ? (
          <div className={s.dialogFoot} data-overlay-part="footer">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * A dialog that asks before an action: its fields, the API's refusal, and the footer with Cancel (or `cancelLabel`,
 * Back on a stepped dialog) on the left and one primary Confirm on the right. Enter in a field submits the form.
 */
export function ConfirmDialog({
  open,
  title,
  subtitle,
  head,
  onClose,
  onConfirm,
  onCancel,
  busy,
  error,
  confirmLabel = T.own.confirm,
  cancelLabel = T.cancel,
  confirmDisabled,
  danger,
  wide,
  messages,
  children,
}: {
  open: boolean;
  title: string;
  subtitle?: ReactNode;
  head?: ReactNode;
  onClose: () => void;
  onConfirm: () => void;
  /** The left footer button (default: close). */
  onCancel?: () => void;
  busy?: boolean;
  error?: unknown;
  confirmLabel?: string;
  cancelLabel?: string;
  confirmDisabled?: boolean;
  danger?: boolean;
  wide?: boolean;
  messages?: ErrorTexts;
  children?: ReactNode;
}) {
  const formId = useId();
  return (
    <Dialog
      open={open}
      title={title}
      subtitle={subtitle}
      head={head}
      onClose={onClose}
      wide={wide}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel ?? onClose}>
            {cancelLabel}
          </Button>
          <Button type="submit" form={formId} variant={danger ? "danger" : "primary"} busy={busy} disabled={confirmDisabled}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          // review of round 1: a closing dialog is inert, and a submit that still arrives (Enter) is dropped, so an
          // append-only write such as a note is never sent twice
          if (!open || busy) return;
          onConfirm();
        }}
      >
        {children}
        <ErrorBanner error={error} messages={messages} />
      </form>
    </Dialog>
  );
}

/**
 * The large modal (1040 px wide, up to 86% of the window height; full screen on phones): a header, a scrolling body
 * and a footer fixed at the bottom.
 */
export function Modal({
  open,
  title,
  onClose,
  header,
  footer,
  children,
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  /** More under the title (the facts). */
  header?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const { mounted, closing } = usePresence(open, DURATION.med);
  useOverlay(ref, open, onClose);
  if (!mounted) return null;
  return (
    <div
      className={cx(s.overlay, s.center, closing && s.closing)}
      inert={closing || undefined}
      data-closing={closing || undefined}
      onClick={(e) => !closing && e.target === e.currentTarget && onClose()}
    >
      <div
        ref={ref}
        className={cx(s.modal, closing && s.closing)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className={s.modalHead}>
          <div className={s.modalTop}>
            <h2 id={titleId}>{title}</h2>
            <CloseButton onClose={onClose} />
          </div>
          {header}
        </div>
        <div className={s.modalBody} data-overlay-part="body">
          {children}
        </div>
        {footer ? (
          <div className={s.modalFoot} data-overlay-part="footer">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The side panel: a 480 px drawer from the right (full width on phones) for details on demand; `wide` makes it 760 px
 * (the remarks history and a user's details, design case-workspace-admin, decisions 15 and 23).
 */
export function SidePanel({
  open,
  title,
  onClose,
  footer,
  wide,
  children,
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const { mounted, closing } = usePresence(open, DURATION.slow);
  useOverlay(ref, open, onClose);
  if (!mounted) return null;
  return (
    <div
      className={cx(s.overlay, closing && s.closing)}
      inert={closing || undefined}
      data-closing={closing || undefined}
      onClick={(e) => !closing && e.target === e.currentTarget && onClose()}
    >
      <div
        ref={ref}
        className={cx(s.panel, wide && s.panelWide, closing && s.closing)}
        data-panel={wide ? "wide" : undefined}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className={s.panelHead}>
          <h2 id={titleId}>{title}</h2>
          <CloseButton onClose={onClose} />
        </div>
        <div className={s.panelBody} data-overlay-part="body">
          {children}
        </div>
        {footer ? (
          <div className={s.panelFoot} data-overlay-part="footer">
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export interface MenuItem {
  key: string;
  label: ReactNode;
  href?: string;
  onSelect?: () => void;
  /** Marks the item as the current page (`aria-current`). */
  current?: boolean;
  /** Drawn in red (a destructive action such as End Membership, design portal-ui-polish-2, decision 34). */
  danger?: boolean;
  /** A separator line before the item. */
  separator?: boolean;
}

const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/** The gap between the button and the list, and the least margin kept inside the viewport (design case-inbox-simplify,
 * decision 23). */
const MENU_GAP = 4;
const MENU_EDGE = 8;

/**
 * Where the list of a `Menu` goes, from the button's rectangle (design case-inbox-simplify, decision 23): below the
 * button, or above it when the room below is under the list's height and the room above is larger; aligned to the
 * button's start or end edge; kept `MENU_EDGE` px inside the viewport on both sides. `position: fixed`.
 */
export function menuPlacement(
  rect: Pick<DOMRect, "top" | "bottom" | "left" | "right">,
  list: { width: number; height: number },
  view: { width: number; height: number },
  align: "start" | "end",
): CSSProperties {
  const below = view.height - rect.bottom - MENU_GAP;
  const above = rect.top - MENU_GAP;
  const up = below < list.height && above > below;
  const wanted = align === "start" ? rect.left : rect.right - list.width;
  const left = Math.max(MENU_EDGE, Math.min(wanted, view.width - MENU_EDGE - list.width));
  return up
    ? { position: "fixed", left, bottom: view.height - rect.top + MENU_GAP }
    : { position: "fixed", left, top: rect.bottom + MENU_GAP };
}

/**
 * An accessible dropdown (decision 17): a button with `aria-expanded`, a list of `menuitem`s, the arrow keys, Home
 * and End move between them, Escape closes and returns the focus to the button, a click outside closes.
 *
 * The list always mounts in a portal, `position: fixed` from the button's rectangle (design case-inbox-simplify,
 * decision 23), so no box that scrolls (the case page's tab bar, a wide table, a side panel) can clip it: in
 * `document.body`, or in the closest `[role='dialog']` when the menu sits in an overlay, so the focus trap holds. It
 * closes on a window resize, on a scroll outside the list that moves the button away from where the list was placed,
 * on a mousedown outside both the button and the list, and on choosing an item. A scroll event that leaves the button
 * where it was (the late event of the tab bar bringing the button into view as it was pressed) is ignored. The first
 * item takes the focus without scrolling anything.
 */
export function Menu({
  label,
  trigger,
  items,
  align = "end",
  triggerClassName,
}: {
  /** The button's accessible name. */
  label: string;
  /** What the button shows (default: the label). */
  trigger?: ReactNode;
  items: MenuItem[];
  align?: "start" | "end";
  triggerClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [host, setHost] = useState<Element | null>(null);
  const [place, setPlace] = useState<CSSProperties>({ position: "fixed" });
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  /** The button's place when the list was placed: a scroll that moves it closes the menu. */
  const anchor = useRef<{ top: number; left: number } | null>(null);
  const listId = useId();

  function itemsEls(): HTMLElement[] {
    return Array.from(list.current?.querySelectorAll<HTMLElement>("[role='menuitem']") ?? []);
  }

  function openMenu() {
    setHost(wrap.current?.closest("[role='dialog']") ?? document.body);
    // a first place from the button alone; the layout effect corrects it with the list's size before the paint (the list
    // is never hidden, so its first item can take the focus at once)
    const b = button.current;
    if (b) {
      const r = b.getBoundingClientRect();
      anchor.current = { top: r.top, left: r.left };
      setPlace(menuPlacement(r, { width: 0, height: 0 }, { width: window.innerWidth, height: window.innerHeight }, align));
    }
    setOpen(true);
  }

  useIsoLayoutEffect(() => {
    if (!open || !host) return;
    const b = button.current;
    const l = list.current;
    if (!b || !l) return;
    const box = l.getBoundingClientRect();
    const r = b.getBoundingClientRect();
    anchor.current = { top: r.top, left: r.left };
    setPlace(
      menuPlacement(
        r,
        { width: l.offsetWidth || box.width, height: l.offsetHeight || box.height },
        { width: window.innerWidth, height: window.innerHeight },
        align,
      ),
    );
  }, [open, host, align]);

  useEffect(() => {
    if (!open || !host) return;
    list.current?.querySelector<HTMLElement>("[role='menuitem']")?.focus({ preventScroll: true });
    const inside = (t: EventTarget | null) =>
      t instanceof Node && (!!wrap.current?.contains(t) || !!list.current?.contains(t));
    const onDown = (e: MouseEvent) => {
      if (!inside(e.target)) setOpen(false);
    };
    const onScroll = (e: Event) => {
      if (e.target instanceof Node && list.current?.contains(e.target)) return;
      const r = button.current?.getBoundingClientRect();
      const at = anchor.current;
      if (!r || !at || Math.abs(r.top - at.top) > 0.5 || Math.abs(r.left - at.left) > 0.5) setOpen(false);
    };
    const onResize = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open, host]);

  function close(returnFocus = true) {
    setOpen(false);
    if (returnFocus) button.current?.focus();
  }

  function onListKey(e: ReactKeyboardEvent<HTMLUListElement>) {
    const els = itemsEls();
    const at = els.indexOf(document.activeElement as HTMLElement);
    let next = -1;
    if (e.key === "ArrowDown") next = (at + 1) % els.length;
    else if (e.key === "ArrowUp") next = (at - 1 + els.length) % els.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = els.length - 1;
    else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
      return;
    } else if (e.key === "Tab") {
      // the list sits outside the button's place in the page: the focus goes back to the button first, so Tab moves
      // on from there
      close();
      return;
    }
    if (next >= 0) {
      e.preventDefault();
      els[next]?.focus({ preventScroll: true });
    }
  }

  function onButtonKey(e: ReactKeyboardEvent<HTMLButtonElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      openMenu();
    }
  }

  const popover = open ? (
    <ul
      ref={list}
      id={listId}
      role="menu"
      aria-label={label}
      className={s.menuList}
      style={place}
      onKeyDown={onListKey}
    >
      {items.map((item) => [
        item.separator ? <li key={`${item.key}-sep`} role="separator" className={s.menuSeparator} /> : null,
        <li key={item.key} role="none" className={item.danger ? s.menuDanger : undefined}>
          {item.href ? (
            <Link
              href={item.href}
              role="menuitem"
              tabIndex={-1}
              aria-current={item.current ? "page" : undefined}
              onClick={() => {
                item.onSelect?.();
                close(false);
              }}
            >
              {item.label}
            </Link>
          ) : (
            <button
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                close();
                item.onSelect?.();
              }}
            >
              {item.label}
            </button>
          )}
        </li>,
      ])}
    </ul>
  ) : null;

  return (
    <div className={s.menu} ref={wrap}>
      <button
        ref={button}
        type="button"
        className={triggerClassName ?? s.menuButton}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={label}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={onButtonKey}
      >
        {trigger ?? label}
      </button>
      {popover && host ? createPortal(popover, host) : null}
    </div>
  );
}
