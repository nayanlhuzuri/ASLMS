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
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";

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
 * `data-overlay-part`; an overlay without the marks (the phone drawer) is searched as a whole.
 */
export function firstFocus(root: HTMLElement): HTMLElement {
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

/** The side panel: a 480 px drawer from the right (full width on phones) for details on demand. */
export function SidePanel({
  open,
  title,
  onClose,
  footer,
  children,
}: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
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
        className={cx(s.panel, closing && s.closing)}
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
}

/**
 * An accessible dropdown (decision 17): a button with `aria-expanded`, a list of `menuitem`s, the arrow keys, Home
 * and End move between them, Escape closes and returns the focus to the button, a click outside closes.
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
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const listId = useId();

  function itemsEls(): HTMLElement[] {
    return Array.from(wrap.current?.querySelectorAll<HTMLElement>("[role='menuitem']") ?? []);
  }

  useEffect(() => {
    if (!open) return;
    wrap.current?.querySelector<HTMLElement>("[role='menuitem']")?.focus();
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

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
      close(false);
      return;
    }
    if (next >= 0) {
      e.preventDefault();
      els[next]?.focus();
    }
  }

  function onButtonKey(e: ReactKeyboardEvent<HTMLButtonElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setOpen(true);
    }
  }

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
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onButtonKey}
      >
        {trigger ?? label}
      </button>
      {open ? (
        <ul id={listId} role="menu" aria-label={label} className={cx(s.menuList, align === "start" && s.menuStart)} onKeyDown={onListKey}>
          {items.map((item) => (
            <li key={item.key} role="none">
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
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
