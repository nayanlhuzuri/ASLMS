"use client";

/**
 * Feedback of the UI kit (design portal-ui-redesign, decisions 10.6, 10.14, 11, 17 and 19): badges with fixed colour
 * meanings, the error banner with Retry, notices, skeletons while loading (with the visually hidden "Loading" status
 * text), empty states with an icon circle and a title, the score and severity badges, signal chips, the meter and
 * the stepper. Colour is never the only signal: every badge carries words. The confirmation toast (`ToastProvider`,
 * `useToast`, design portal-motion, decisions 1 to 8) confirms an action just done on a shell page.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { clearFlash, peekFlash } from "@/lib/flash";
import { errorText, T, type ErrorTexts } from "@/lib/messages";
import { signalText, type Signal } from "@/lib/signals";
import { labelFor } from "@/lib/displayLabels";
import { hearingBand } from "@/lib/hearingDate";

import { Button, cx } from "./controls";
import s from "./feedback.module.css";
import { DURATION, usePresence } from "./motion";
import { OfficeName } from "./OfficeName";

/** Red = urgent or overdue; ochre (`warning`) = due soon; green = done or confirmed; navy (`info`) = action or selection; none = neutral. */
export type Tone = "danger" | "warning" | "success" | "info";

/**
 * A badge. `look` (design dashboard-my-work-polish, decision 14) draws the tone's colour as a fill (`solid`) or as an
 * outline on the surface (`outline`), rendered as `data-look`; without it the tone's soft ground, as before.
 */
export function Badge({
  tone,
  title,
  look,
  wrap,
  children,
}: {
  tone?: Tone;
  title?: string;
  look?: "solid" | "outline";
  /** The text wraps at word boundaries instead of being cut: for a badge that names an office, so a long name never
   * widens its table column (design portal-names-and-labels, deviation 9). */
  wrap?: boolean;
  children: ReactNode;
}) {
  return (
    <span
      className={cx(s.badge, tone && s[`badge-${tone}`])}
      data-look={look}
      data-wrap={wrap ? "" : undefined}
      title={title ?? (typeof children === "string" ? children : undefined)}
    >
      <span className={s.badgeText}>{children}</span>
    </span>
  );
}

export function ErrorBanner({
  error,
  onRetry,
  messages,
  children,
  retrySize = "sm",
}: {
  error: unknown;
  onRetry?: () => void;
  /** The screen's own texts for codes that mean something else elsewhere (design portal-workflow, decision 21). */
  messages?: ErrorTexts;
  /** More after the message (a link to an existing document, for example). */
  children?: ReactNode;
  /** The Try again button's size: `sm` by default; `md` where it stands alone, outside a row (followups-oct, 14). */
  retrySize?: "sm" | "md";
}) {
  if (!error) return null;
  return (
    <div className={s.banner} role="alert" aria-live="assertive">
      <span>{errorText(error, messages)}</span>
      {children}
      {onRetry ? (
        <Button variant="secondary" size={retrySize} onClick={onRetry}>
          {T.retry}
        </Button>
      ) : null}
    </div>
  );
}

/**
 * A short message in the page (design portal-navy-cream, addendum K7): `info` (the default, neutral) for information,
 * `success` (green) for the confirmation of an action just done, `warning` (ochre) for something to report or act on.
 */
export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "success" | "warning" }) {
  return (
    <div className={s.notice} role="status" aria-live="polite" data-tone={tone}>
      {children}
    </div>
  );
}

/** Grey shimmering bars in the shape of the content; hidden from screen readers. */
export function Skeleton({ lines = 3, width }: { lines?: number; width?: string }) {
  return (
    <span className={s.skeletonGroup} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className={s.skeleton} style={width ? { width } : undefined} />
      ))}
    </span>
  );
}

/** While a list or panel loads: skeleton rows and the visually hidden status text "Loading…". */
export function Loading({ lines = 3 }: { lines?: number }) {
  return (
    <span className={s.loading} role="status" aria-live="polite">
      <span className="visually-hidden">{T.loading}</span>
      <Skeleton lines={lines} />
    </span>
  );
}

function EmptyIcon() {
  return (
    <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 13h5l1 3h6l1-3h5" />
      <path d="M5 13 7 5h10l2 8v6H5z" />
    </svg>
  );
}

/** An empty list: the icon circle, an optional title, and one line saying when items appear. */
export function EmptyState({
  title,
  icon,
  children,
  compact = false,
}: {
  title?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  /**
   * The light form for an empty list inside a card or panel (design portal-ui-kit-fixes, decisions 17 and 18): no
   * frame, no icon, left-aligned muted text, the title (when given) in the text colour.
   */
  compact?: boolean;
}) {
  if (compact) {
    return (
      <div className={s.emptyCompact} data-compact="">
        {title ? <p className={s.emptyTitle}>{title}</p> : null}
        {children ? <div className={s.emptyText}>{children}</div> : null}
      </div>
    );
  }
  return (
    <div className={s.empty}>
      <span className={s.emptyIcon}>{icon ?? <EmptyIcon />}</span>
      {title ? <p className={s.emptyTitle}>{title}</p> : null}
      {children ? <div className={s.emptyText}>{children}</div> : null}
    </div>
  );
}

/**
 * The score as stored (three decimals) with the label of the API's `band`: "Strong · 0.950" solid navy for `high`,
 * "Possible · 0.620" outlined navy for `medium` (decision 10.6, addendum C4). The colour and the label never come from the portal
 * comparing numbers, because the bands are the super admin's settings.
 */
export function ScoreBadge({ score, band }: { score: number; band: string }) {
  const known = (T.score as Record<string, unknown>)[band];
  const label = band === "high" || band === "medium" ? (known as string) : band.charAt(0).toUpperCase() + band.slice(1);
  // design portal-navy-cream, addendum C4: one recommendation tone on every screen, strong solid navy, possible outlined
  const look = band === "high" ? "solid" : band === "medium" ? "outline" : undefined;
  return (
    <Badge tone={look ? "info" : undefined} look={look}>
      {T.score.badge(label, score.toFixed(3))}
    </Badge>
  );
}

/**
 * A department and its score (design portal-screen-fixes-work, decision 20): the department's name (`OfficeName`) first,
 * then the `ScoreBadge`, which wraps under the name in a narrow cell, never inside itself. Without a band (a best score
 * below the possible band) the name and the muted plain score, with no badge: no recommendation exists there.
 */
export function ScoreLine({
  office,
  score,
  band,
}: {
  office: { code: string | null | undefined; name?: string | null };
  score: number;
  band: string | null | undefined;
}) {
  return (
    <span className={s.scoreLine} data-score-line="">
      <OfficeName code={office.code} name={office.name} />
      {band ? <ScoreBadge score={score} band={band} /> : <span className="muted">{score.toFixed(3)}</span>}
    </span>
  );
}

/** The alert kinds about a hearing, whose `data.hearing_date` gives the badge its band (as on the dashboard). */
const HEARING_ALERT_KINDS = new Set(["hearing_due", "listed_tomorrow"]);

/**
 * The colour of an alert's badge by what the alert means, never by its severity (design portal-navy-cream, addendum
 * A1, with dashboard-my-work-polish decision 6): a hearing alert takes its hearing date's band (today and tomorrow red,
 * 2 to 7 days ochre, otherwise neutral); a recommendation is navy, solid when strong and outlined when possible; every
 * other alert is neutral.
 */
export function alertTone(
  kind: string | undefined,
  data: Record<string, unknown> | undefined,
  now?: Date,
): { tone?: Tone; look?: "solid" | "outline" } {
  if (kind && HEARING_ALERT_KINDS.has(kind) && typeof data?.hearing_date === "string") {
    const { band } = hearingBand(data.hearing_date, { now });
    if (band === "today" || band === "tomorrow") return { tone: "danger" };
    if (band === "week") return { tone: "warning" };
    return {};
  }
  if (kind === "recommendation") {
    if (data?.band === "high") return { tone: "info", look: "solid" };
    if (data?.band === "medium") return { tone: "info", look: "outline" };
  }
  return {};
}

/** The API's severity of an alert (critical / high / normal) in words; its colour follows the alert's meaning. */
export function SeverityBadge({ severity, kind, data }: { severity: string; kind?: string; data?: Record<string, unknown> }) {
  const { tone, look } = alertTone(kind, data);
  return (
    <Badge tone={tone} look={look}>
      {labelFor(T.wf.severity, severity)}
    </Badge>
  );
}

export function SignalChip({ signal }: { signal: Signal }) {
  return <span className={s.signal}>{signalText(signal)}</span>;
}

export function SignalChips({ signals }: { signals: Signal[] }) {
  if (signals.length === 0) return null;
  return (
    <ul className={s.signals} aria-label={T.kit.signals}>
      {signals.map((sig, i) => (
        <li key={i}>
          <SignalChip signal={sig} />
        </li>
      ))}
    </ul>
  );
}

/** A filled bar for a value from 0 to 1 (the match strength), filling over 700 ms. */
export function Meter({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div className={s.meter} role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={1} aria-valuenow={v}>
      <i className={s.meterFill} style={{ width: `${(v * 100).toFixed(1)}%` }} />
    </div>
  );
}

/** The progress bars of a stepped dialog and its "Step n of 3 · …" line (decision 25). */
export function Stepper({ step, steps }: { step: number; steps: string[] }) {
  const current = Math.max(1, Math.min(step, steps.length));
  return (
    <div className={s.stepper}>
      <div className={s.steps} aria-hidden="true">
        {steps.map((label, i) => (
          <span key={label} className={cx(s.step, i < current && s.stepDone)}>
            <i />
          </span>
        ))}
      </div>
      <p className={s.stepLabel} aria-live="polite">
        {T.kit.step(current, steps.length, steps[current - 1] ?? "")}
      </p>
    </div>
  );
}

/** The tones of a progress segment (design data-collection-redesign, decision 9). */
export type ProgressTone = "done" | "active" | "waiting" | "unavailable" | "failed";

export interface ProgressSegment {
  tone: ProgressTone;
  value: number;
}

const PROGRESS_ORDER: readonly ProgressTone[] = ["done", "active", "waiting", "unavailable", "failed"];

/**
 * A segmented progress bar (decision 9): done is solid green, active navy with the live pulse, waiting striped
 * navy-soft, unavailable slate with a strong edge, failed red. `role="progressbar"` with the done amount as
 * `aria-valuenow` of `max` and `text` as `aria-valuetext`; the same text is shown under the bar (never colour alone)
 * unless the caller shows it beside the bar (`showText={false}`). Each segment grows by `scaleX` over `--slow`; under
 * reduced motion nothing animates. Nothing moves the layout.
 */
export function ProgressBar({
  segments,
  max,
  label,
  text,
  size = "md",
  showText = true,
}: {
  segments: ProgressSegment[];
  /** The whole (defaults to the sum of the segments). */
  max?: number;
  label: string;
  text: string;
  size?: "sm" | "md";
  showText?: boolean;
}) {
  const total = Math.max(0, max ?? segments.reduce((sum, seg) => sum + Math.max(0, seg.value), 0));
  const done = segments.filter((seg) => seg.tone === "done").reduce((sum, seg) => sum + Math.max(0, seg.value), 0);
  const ordered = [...segments].sort((a, b) => PROGRESS_ORDER.indexOf(a.tone) - PROGRESS_ORDER.indexOf(b.tone));
  // the segments never add up past the whole, so the track never holds more than it shows
  let room = 100;
  const widths = ordered.map((seg) => {
    const w = total > 0 ? Math.max(0, Math.min(room, (Math.max(0, seg.value) / total) * 100)) : 0;
    room -= w;
    return w;
  });
  return (
    <div className={s.progress}>
      <div
        className={cx(s.progressTrack, size === "sm" ? s.progressSm : s.progressMd)}
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={Math.min(done, total)}
        aria-valuetext={text}
      >
        {total > 0
          ? ordered.map((seg, i) =>
              widths[i]! > 0 ? (
                <i
                  key={seg.tone}
                  className={cx(s.progressSeg, s[`seg-${seg.tone}`])}
                  data-tone={seg.tone}
                  style={{ width: `${widths[i]!.toFixed(2)}%` }}
                />
              ) : null,
            )
          : null}
      </div>
      {showText ? <span className={s.progressText}>{text}</span> : null}
    </div>
  );
}

/** The legend of a segmented bar: a swatch per tone with its words (and count when given). */
export function ProgressLegend({ items }: { items: { tone: ProgressTone; label: string; value?: string }[] }) {
  return (
    <ul className={s.legend} aria-label={T.kit.legend}>
      {items.map((it) => (
        <li key={it.tone}>
          <i className={cx(s.swatch, s[`seg-${it.tone}`])} aria-hidden="true" />
          <span>{it.label}</span>
          {it.value !== undefined ? <b>{it.value}</b> : null}
        </li>
      ))}
    </ul>
  );
}

/** How long a text-only toast stays, in milliseconds (design portal-motion, decision 4). */
export const TOAST_MS = 6000;

/** The link a toast may carry (Case Claim's Open Case Page). */
export interface ToastLink {
  href: string;
  label: string;
}

type ToastFn = (text: string, link?: ToastLink) => void;

const ToastContext = createContext<ToastFn | null>(null);

/**
 * The function that raises the confirmation toast: `toast(text, link?)`. Outside a `ToastProvider` it throws, so a
 * confirmation is never lost silently (design portal-motion, decision 1).
 */
export function useToast(): ToastFn {
  const toast = useContext(ToastContext);
  if (!toast) throw new Error("useToast() needs a ToastProvider above it (PortalShell holds one for the shell pages)");
  return toast;
}

/** A check in a circle (the toast's mark), hidden from screen readers. */
export function CheckIcon({ size = 18 }: { size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12.5 2.5 2.5L16 9.5" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

interface ToastState {
  text: string;
  link: ToastLink | null;
  /** Raised on every `toast()`, so a replacement restarts the timer. */
  seq: number;
}

/**
 * The confirmation toast (design portal-motion, decisions 1 to 8): renders its children, then the toast host as its last
 * child. One toast at a time; a new one replaces the text in place and restarts the timer. A text-only toast closes
 * after `TOAST_MS`, paused while the pointer is over it or focus is inside it; a toast with a link stays until Close,
 * Escape, a new toast or a change of page. A flash left by the previous page (`lib/flash.ts`) is shown on mount and on
 * every change of pathname, then cleared; a change of the query string closes nothing. The toast never takes focus. A
 * visually hidden polite status region, always in the document, carries the words to screen readers; the visible card
 * is a group named by them, its text hidden from screen readers so it is not read twice.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const [current, setCurrent] = useState<ToastState | null>(null);
  const [open, setOpen] = useState(false);
  const [hover, setHover] = useState(false);
  const [focused, setFocused] = useState(false);
  const seq = useRef(0);
  const card = useRef<HTMLDivElement>(null);
  // the element focus came from when it entered the toast, given back when the toast closes under it
  const returnFocus = useRef<HTMLElement | null>(null);
  const lastPath = useRef<string | null>(null);
  const presence = usePresence(open, DURATION.med);

  const show = useCallback<ToastFn>((text, link) => {
    seq.current += 1;
    setCurrent({ text, link: link ?? null, seq: seq.current });
    setOpen(true);
  }, []);

  const close = useCallback(() => {
    const el = card.current;
    if (el && typeof document !== "undefined" && el.contains(document.activeElement)) {
      const back = returnFocus.current;
      if (back && back.isConnected) back.focus();
      else (document.activeElement as HTMLElement | null)?.blur();
    }
    returnFocus.current = null;
    setHover(false);
    setFocused(false);
    setOpen(false);
  }, []);

  // the flash of the previous page, on mount and on every change of pathname; otherwise a change of page closes it
  useEffect(() => {
    const changed = lastPath.current !== null && lastPath.current !== pathname;
    lastPath.current = pathname;
    const flash = peekFlash();
    if (flash) {
      clearFlash();
      show(flash);
    } else if (changed) close();
  }, [pathname, show, close]);

  // the timer of a text-only toast, paused while hovered or focused; leaving starts the full time again
  const seqNow = current?.seq;
  const hasLink = !!current?.link;
  useEffect(() => {
    if (!open || hasLink || hover || focused) return;
    const timer = setTimeout(close, TOAST_MS);
    return () => clearTimeout(timer);
  }, [open, hasLink, hover, focused, seqNow, close]);

  // the words stay until the exit ends; then the card is empty (and hidden)
  const shown = presence.mounted ? current : null;

  function onFocus(e: FocusEvent<HTMLDivElement>) {
    const from = e.relatedTarget as HTMLElement | null;
    if (!e.currentTarget.contains(from)) returnFocus.current = from;
    setFocused(true);
  }
  function onBlur(e: FocusEvent<HTMLDivElement>) {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
  }
  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Escape") return;
    e.stopPropagation();
    close();
  }

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className={s.toastHost} data-motion-layer="" data-ui="toast-host">
        <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true" data-ui="toast-status">
          {shown ? (shown.link ? `${shown.text} ${shown.link.label}` : shown.text) : ""}
        </div>
        <div
          ref={card}
          className={s.toast}
          role="group"
          aria-label={shown?.text}
          data-ui="toast"
          data-open={open && shown ? "" : undefined}
          data-closing={presence.closing && shown ? "" : undefined}
          onMouseEnter={() => setHover(true)}
          onMouseLeave={() => setHover(false)}
          onFocus={onFocus}
          onBlur={onBlur}
          onKeyDown={onKeyDown}
        >
          {shown ? (
            <>
              <span className={s.toastIcon}>
                <CheckIcon />
              </span>
              <span className={s.toastText} aria-hidden="true">
                {shown.text}
              </span>
              {shown.link ? (
                <Link href={shown.link.href} className={s.toastLink}>
                  {shown.link.label}
                </Link>
              ) : null}
              <button type="button" className={s.toastClose} aria-label={T.kit.closeMessage} onClick={close}>
                <CloseIcon />
              </button>
            </>
          ) : null}
        </div>
      </div>
    </ToastContext.Provider>
  );
}
