"use client";

/**
 * Layout of the UI kit (design portal-ui-redesign, decisions 10.2, 13, 16 and 17): the card, the page header with
 * the breadcrumb inside the page above the title and at most one primary action, the breadcrumb itself, tabs with
 * the sliding underline, counts and a "More" group, tiles, the headline number (`Kpi`), the collapsible and the
 * Settings template's frame (`SettingsLayout`).
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { crumbLabel } from "@/lib/routes";

import { cx, SelectField } from "./controls";
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
  id,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  /** No body padding (a table or a list that runs to the edges). */
  flush?: boolean;
  /** An anchor for in-page links (the Jump To list of the user-type page). */
  id?: string;
}) {
  return (
    <section className={s.card} id={id}>
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
 * tab's label when one of its items is current. Tab rows scroll sideways rather than clip: the row carries
 * `data-scroll-x`, one of the two places the browser check (`frontend/e2e`, design portal-ui-polish, decision 21)
 * allows to scroll sideways, because a row of tabs on a phone is better scrolled than wrapped or cut.
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
    // design portal-ui-polish, decision 1: one observer on the row and on every tab, so the underline follows a
    // tab's own width (a count arriving, Inter loading after first paint); once more when the fonts are ready
    let live = true;
    const fonts = typeof document !== "undefined" ? (document as Document & { fonts?: FontFaceSet }).fonts : undefined;
    fonts?.ready?.then(() => {
      if (live) place();
    });
    if (typeof ResizeObserver === "undefined") {
      return () => {
        live = false;
      };
    }
    const observer = new ResizeObserver(place);
    observer.observe(el);
    el.querySelectorAll<HTMLElement>("[data-tab]").forEach((tab) => observer.observe(tab));
    return () => {
      live = false;
      observer.disconnect();
    };
  }, [activeKey, items.length, more?.length]);

  const moreCurrent = (more ?? []).find((t) => t.active);
  return (
    <nav aria-label={label} className={s.tabs} ref={nav} data-scroll-x="">
      {items.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          className={s.tab}
          data-tab=""
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
        <span className={s.tabMore} data-tab="" data-tab-current={moreCurrent ? "true" : undefined}>
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
  onToggle,
  children,
}: {
  summary: ReactNode;
  /** Always shown under the summary button, outside it (a row's own facts, which may hold their own controls). */
  after?: ReactNode;
  defaultOpen?: boolean;
  /** Told each time the section opens or closes (the console's full answer is fetched on each opening). */
  onToggle?: (open: boolean) => void;
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
          setOpen(!open);
          setOpened(true);
          onToggle?.(!open);
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

export interface SettingsItem {
  key: string;
  label: string;
  href: string;
  active: boolean;
}

/**
 * The Settings template (design portal-ui-redesign, decision 26): a sub-menu of the setting groups on the left on
 * laptops (links, `aria-current` on the current one), a select on phones, and one setting group at a time beside it.
 */
export function SettingsLayout({
  label,
  selectLabel,
  items,
  children,
}: {
  /** The accessible name of the sub-menu. */
  label: string;
  /** The phone select's label. */
  selectLabel: string;
  items: SettingsItem[];
  children: ReactNode;
}) {
  const router = useRouter();
  const current = items.find((i) => i.active) ?? items[0];
  return (
    <div className={s.settings}>
      <nav aria-label={label} className={s.settingsNav}>
        <ul>
          {items.map((i) => (
            <li key={i.key}>
              <Link href={i.href} className={s.settingsLink} aria-current={i.active ? "page" : undefined}>
                {i.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <div className={s.settingsSelect}>
        <SelectField
          label={selectLabel}
          value={current?.key ?? ""}
          options={items.map((i) => ({ value: i.key, label: i.label }))}
          onChange={(e) => {
            const next = items.find((i) => i.key === e.target.value);
            if (next) router.push(next.href);
          }}
        />
      </div>
      <div className={s.settingsBody}>{children}</div>
    </div>
  );
}
