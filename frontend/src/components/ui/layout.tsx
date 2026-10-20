"use client";

/**
 * Layout of the UI kit (design portal-ui-redesign, decisions 10.2, 13, 16 and 17): the card, the page header with
 * the breadcrumb inside the page above the title and at most one primary action, the breadcrumb itself, tabs with
 * the sliding underline, counts and a "More" group, tiles, the headline number (`Kpi`) and the collapsible.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { crumbLabel } from "@/lib/routes";

import { cx } from "./controls";
import s from "./layout.module.css";
import { useCountUp } from "./motion";
import { Menu } from "./overlays";

// a layout effect in the browser (the underline is placed before paint), a plain effect on the server
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/** A card with an optional head (title and actions) and a body. */
export function Card({
  title,
  actions,
  children,
  flush,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  /** No body padding (a table or a list that runs to the edges). */
  flush?: boolean;
}) {
  return (
    <section className={s.card}>
      {title || actions ? (
        <div className={s.cardHead}>
          {title ? <h3>{title}</h3> : <span />}
          {actions ? <div className={s.cardActions}>{actions}</div> : null}
        </div>
      ) : null}
      <div className={cx(s.cardBody, flush && s.flush)}>{children}</div>
    </section>
  );
}

/** The breadcrumb of the current path (`Dashboard / Section / Page`), inside the page above the title. */
export function Breadcrumb() {
  const pathname = usePathname() ?? "/";
  const parts = pathname.split("/").filter(Boolean);
  const crumbs = [{ href: "/", label: T.dash.title }];
  parts.forEach((_part, i) => {
    const href = "/" + parts.slice(0, i + 1).join("/");
    crumbs.push({ href, label: crumbLabel(href) });
  });
  return (
    <nav aria-label={T.shell.breadcrumb} className={s.crumbs}>
      <ol>
        {crumbs.map((c, i) => (
          <li key={c.href}>
            {i === crumbs.length - 1 ? <span aria-current="page">{c.label}</span> : <Link href={c.href}>{c.label}</Link>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/**
 * The page header (decision 16): the breadcrumb, the title, an optional subtitle, one `primary` slot (at most one
 * blue button per page) and secondary actions.
 */
export function PageHeader({
  title,
  subtitle,
  primary,
  actions,
  crumbs = true,
  titleClassName,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  primary?: ReactNode;
  actions?: ReactNode;
  crumbs?: boolean;
  titleClassName?: string;
}) {
  return (
    <header className={s.pageHeader}>
      {crumbs ? <Breadcrumb /> : null}
      <div className={s.pageHead}>
        <div className={s.pageTitle}>
          <h1 className={titleClassName}>{title}</h1>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {actions || primary ? (
          <div className={s.pageActions}>
            {actions}
            {primary}
          </div>
        ) : null}
      </div>
    </header>
  );
}

export interface TabItem {
  href: string;
  label: string;
  active: boolean;
  /** A count in a pill after the label. */
  count?: number | null;
}

/**
 * Tabs as links, one route each (`aria-current` on the current one), with the sliding underline measured from the
 * current tab, a count per tab, and an optional `more` group shown as a "More" menu whose button takes the current
 * tab's label when one of its items is current. Tab rows scroll sideways rather than clip.
 */
export function Tabs({ items, label, more }: { items: TabItem[]; label: string; more?: TabItem[] }) {
  const nav = useRef<HTMLElement>(null);
  const [ink, setInk] = useState<{ left: number; width: number } | null>(null);
  const activeKey = [...items, ...(more ?? [])].find((t) => t.active)?.href ?? "";

  useIsoLayoutEffect(() => {
    const el = nav.current;
    if (!el) return;
    const place = () => {
      const current = el.querySelector<HTMLElement>("[data-tab-current='true']");
      setInk(current ? { left: current.offsetLeft, width: current.offsetWidth } : null);
    };
    place();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(place);
    observer.observe(el);
    return () => observer.disconnect();
  }, [activeKey, items.length]);

  const moreCurrent = (more ?? []).find((t) => t.active);
  return (
    <nav aria-label={label} className={s.tabs} ref={nav}>
      {items.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          className={s.tab}
          aria-current={t.active ? "page" : undefined}
          data-tab-current={t.active ? "true" : undefined}
        >
          {t.label}
          {t.count !== undefined && t.count !== null ? (
            <span className={s.tabCount} aria-hidden="true">
              {formatNumber(t.count)}
            </span>
          ) : null}
          {t.count !== undefined && t.count !== null ? <span className="visually-hidden"> ({formatNumber(t.count)})</span> : null}
        </Link>
      ))}
      {more && more.length > 0 ? (
        <span className={s.tabMore} data-tab-current={moreCurrent ? "true" : undefined}>
          <Menu
            label={moreCurrent ? moreCurrent.label : T.kit.more}
            trigger={
              <>
                {moreCurrent ? moreCurrent.label : T.kit.more}
                <span aria-hidden="true"> ▾</span>
              </>
            }
            triggerClassName={cx(s.tab, s.tabMoreButton, moreCurrent && s.tabMoreCurrent)}
            items={more.map((t) => ({ key: t.href, href: t.href, label: t.label, current: t.active }))}
            align="start"
          />
        </span>
      ) : null}
      {ink ? <span className={s.ink} aria-hidden="true" style={{ left: ink.left, width: ink.width }} data-testid="tab-ink" /> : null}
    </nav>
  );
}

/** A figure with its label; with `href` the whole tile is one link named by its label and value. */
export function Tile({
  label,
  value,
  sub,
  href,
}: {
  label: string;
  value: number | null | undefined;
  sub?: ReactNode;
  href?: string;
}) {
  const body = (
    <>
      <div className={s.tileValue}>{formatNumber(value)}</div>
      <div className={s.tileLabel}>{label}</div>
      {sub ? <div className={s.tileSub}>{sub}</div> : null}
    </>
  );
  if (href) {
    return (
      <Link href={href} className={cx(s.tile, s.tileLink)} aria-label={`${label}: ${formatNumber(value)}`}>
        {body}
      </Link>
    );
  }
  return <div className={s.tile}>{body}</div>;
}

/**
 * A headline number (decision 17): the label, the value counting up (at once under reduced motion), a sub line in
 * a status tone, and an optional link. The accessible name always carries the final value.
 */
export function Kpi({
  label,
  value,
  sub,
  tone,
  href,
}: {
  label: string;
  value: number | null | undefined;
  sub?: ReactNode;
  tone?: "danger" | "warning";
  href?: string;
}) {
  const shown = useCountUp(value);
  const body = (
    <>
      <div className={s.kpiLabel}>{label}</div>
      <div className={s.kpiValue} aria-hidden={href ? true : undefined}>
        {formatNumber(shown)}
      </div>
      {sub ? <div className={cx(s.kpiSub, tone && s[`kpiSub-${tone}`])}>{sub}</div> : null}
    </>
  );
  if (href) {
    return (
      <Link href={href} className={cx(s.kpi, s.kpiLink)} aria-label={`${label}: ${formatNumber(value)}`}>
        {body}
      </Link>
    );
  }
  return <div className={s.kpi}>{body}</div>;
}

/**
 * A `<details>`-like section (decision 16): the summary button toggles `aria-expanded`, and the body opens
 * smoothly (`grid-template-rows 0fr -> 1fr`). The body mounts on first opening and stays mounted, out of the tab
 * order while closed.
 */
export function Collapsible({
  summary,
  after,
  defaultOpen = false,
  children,
}: {
  summary: ReactNode;
  /** Always shown under the summary button, outside it (a row's own facts, which may hold their own controls). */
  after?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [opened, setOpened] = useState(defaultOpen);
  const bodyId = useId();
  return (
    <div className={cx(s.collapsible, open && s.open)}>
      <button
        type="button"
        className={s.summary}
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => {
          setOpen((v) => !v);
          setOpened(true);
        }}
      >
        <svg className={s.chev} aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m9 6 6 6-6 6" />
        </svg>
        <span>{summary}</span>
      </button>
      {after ? <div className={s.after}>{after}</div> : null}
      <div id={bodyId} className={s.body} inert={!open} aria-hidden={!open}>
        <div className={s.bodyInner}>{opened ? children : null}</div>
      </div>
    </div>
  );
}
