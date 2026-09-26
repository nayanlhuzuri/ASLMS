"use client";

import { useEffect, useId, useRef, type FormEvent, type ReactNode } from "react";
import { Button } from "./Button";
import { Icon } from "./Icon";
import s from "./ui.module.css";

/**
 * Modal dialog on the native <dialog> element: focus moves into it on open, Escape closes it, the page behind is
 * inert, and focus returns to the element that opened it.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  onSubmit,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  onSubmit?: (e: FormEvent<HTMLFormElement>) => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) {
      opener.current = document.activeElement;
      el.showModal();
      const first = el.querySelector<HTMLElement>("[data-autofocus], input:not([type=hidden]), select, textarea");
      first?.focus();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handleClose = () => {
      const o = opener.current;
      if (o instanceof HTMLElement) o.focus();
      if (open) onClose();
    };
    el.addEventListener("close", handleClose);
    return () => el.removeEventListener("close", handleClose);
  }, [open, onClose]);

  const body = (
    <div className={s.dialogInner}>
      <div className={s.dialogHead}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <h2 id={titleId}>{title}</h2>
          {description ? (
            <p id={descId} className="muted" style={{ fontSize: 14 }}>
              {description}
            </p>
          ) : null}
        </div>
        <button type="button" className={s.iconButton} aria-label="Close" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      {children}
      {footer ? <div className={s.formActions}>{footer}</div> : null}
    </div>
  );

  return (
    <dialog
      ref={ref}
      className={s.dialog}
      style={wide ? { width: "min(760px, calc(100vw - 32px))" } : undefined}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      {open ? (
        onSubmit ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onSubmit(e);
            }}
          >
            {body}
          </form>
        ) : (
          body
        )
      ) : null}
    </dialog>
  );
}

/** A simple confirm/cancel footer for form dialogs. */
export function DialogButtons({ submitLabel, busy, onCancel, danger }: { submitLabel: string; busy?: boolean; onCancel: () => void; danger?: boolean }) {
  return (
    <>
      <Button type="submit" variant={danger ? "danger" : "primary"} busy={busy}>
        {submitLabel}
      </Button>
      <Button onClick={onCancel}>Cancel</Button>
    </>
  );
}
