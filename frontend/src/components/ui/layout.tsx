"use client";

/**
 * Layout of the UI kit (design portal-ui-redesign, decisions 10.2, 13, 16 and 17): the card, the page header with
 * the breadcrumb inside the page above the title and at most one primary action, the breadcrumb itself, tabs with
 * the sliding underline, counts and a "More" group, tiles, the headline number (`Kpi`), the collapsible and the
 * Settings template's frame (`SettingsLayout`), and the Filter Card of Layout B (`FilterCard`, design
 * portal-ui-polish-2, decision 21).
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { crumbLabel, CRUMBS_WITHOUT_PAGE } from "@/lib/routes";

import { Button, cx, SelectField } from "./controls";
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
            {i === crumbs.length - 1 ? (
              <span aria-current="page">{c.label}</span>
            ) : CRUMBS_WITHOUT_PAGE.includes(c.href) ? (
              <span>{c.label}</span>
            ) : (
              <Link href={c.href}>{c.label}</Link>
            )}
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
 * `data-scroll-x`, one of the three places the browser check (`frontend/e2e`, design portal-ui-polish, decision 21)
 * allows to scroll sideways, because a row of tabs on a phone is better scrolled than wrapped or cut.
 */
export function Tabs({
  items,
  label,
  more,
  onSelect,
}: {
  items: TabItem[];
  label: string;
  more?: TabItem[];
  /**
   * Takes over a plain click on a tab (the User Details modal keeps its tab in the address without a new history
   * entry, design portal-ui-polish-2, decision 31); a click with a modifier key still opens the link.
   */
  onSelect?: (href: string) => void;
}) {
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
          onClick={
            onSelect
              ? (e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                  e.preventDefault();
                  onSelect(t.href);
                }
              : undefined
          }
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

/**
 * Filter Layout B, "Header Card with Two Zones" (design portal-ui-polish-2, decision 21): the page's one leading
 * control in the left zone (`hero`, 280 px on laptops, on top below 768 px); the other fields in a grid on the right
 * (`repeat(auto-fill, minmax(180px, 1fr))`, labels above the boxes) with the actions in the last cell, Search (the
 * form's submit, when `onSubmit` is given) and More Filters (n), n being the number of set fields inside; More Filters
 * opens a panel inside the card under the right zone (220 ms, at once under reduced motion), open whenever one of its
 * fields is set; and the summary strip under the card (the count, the page's quick links, the applied chips with
 * Clear All). The panel's fields mount on first opening and stay mounted, out of the tab order while closed. The
 * filters themselves stay in the page's query string; the card only draws them. On phones the card stacks: hero,
 * fields, actions, and More Filters opens in place.
 */
export function FilterCard({
  label,
  hero,
  children,
  more,
  moreCount = 0,
  moreOpen,
  onMoreToggle,
  onSubmit,
  submitLabel = T.kit.search,
  submitVariant = "primary",
  actions,
  summary,
}: {
  /** The accessible name of the form (or of the group when there is no submit). */
  label: string;
  /** The left zone: the page's one leading control. */
  hero: ReactNode;
  /** The right zone's fields. */
  children?: ReactNode;
  /** The fields under More Filters (none: no More Filters button). */
  more?: ReactNode;
  /** The number of set fields under More Filters (shown in the button; the panel is open while it is above 0). */
  moreCount?: number;
  /** Controlled open state of More Filters (default: open after a click, or while `moreCount` is above 0). */
  moreOpen?: boolean;
  onMoreToggle?: () => void;
  /** The form's submit: draws Search in the actions cell. */
  onSubmit?: () => void;
  submitLabel?: string;
  submitVariant?: "primary" | "secondary";
  /** More buttons after Search and More Filters (Refresh, Clear). */
  actions?: ReactNode;
  /** The slim line under the card. */
  summary?: ReactNode;
}) {
  const [userOpen, setUserOpen] = useState(false);
  const hasMore = more !== undefined && more !== null && more !== false;
  const open = hasMore && (moreOpen ?? (userOpen || moreCount > 0));
  const [opened, setOpened] = useState(open);
  if (open && !opened) setOpened(true);
  const moreId = useId();
  const toggle = onMoreToggle ?? (() => setUserOpen((o) => !o));
  const hasRight = !!children || !!onSubmit || hasMore || !!actions;
  const hasActions = !!onSubmit || hasMore || !!actions;
  const zonesClass = cx(s.fcZones, !hasRight && s.fcHeroOnly);

  const zones = (
    <>
      <div className={s.fcHero} data-zone="hero">
        {hero}
      </div>
      {hasRight ? (
        <div className={s.fcRight} data-zone="fields">
          <div className={s.fcGrid}>
            {children}
            {hasActions ? (
              <div className={s.fcActions} data-zone="actions">
                {onSubmit ? (
                  <Button type="submit" variant={submitVariant}>
                    {submitLabel}
                  </Button>
                ) : null}
                {hasMore ? (
                  <Button variant="secondary" aria-expanded={open} aria-controls={moreId} onClick={toggle}>
                    {T.kit.moreButton(moreCount)}
                  </Button>
                ) : null}
                {actions}
              </div>
            ) : null}
          </div>
          {hasMore ? (
            <div
              id={moreId}
              className={cx(s.fcMore, open && s.fcMoreOpen)}
              data-zone="more"
              role="group"
              aria-label={T.kit.moreTitle}
              inert={!open}
              aria-hidden={!open}
            >
              <div className={s.fcMoreInner}>{opened ? <div className={s.fcGrid}>{more}</div> : null}</div>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );

  return (
    <div className={s.filterCard} data-filter-card="">
      {/* always the same element, so the hero is not remounted when the page's data adds a submit */}
      <form
        className={zonesClass}
        role={onSubmit ? "search" : "group"}
        aria-label={label}
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit?.();
        }}
      >
        {zones}
      </form>
      {summary ? (
        <div className={s.fcStrip} data-zone="summary">
          {summary}
        </div>
      ) : null}
    </div>
  );
}

/**
 * A long list that scrolls inside its own box (design data-collection-redesign, decision 10; the Department Mapping
 * box moved into the kit): a named, focusable region at most `min(60vh, 560px)` high, with a sticky header row for a
 * table inside it. Every growing list in Data Collection sits in one.
 */
export function ScrollBox({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={s.scrollBox} role="region" aria-label={label} tabIndex={0} data-scroll-y="">
      {children}
    </div>
  );
}

/** Seconds since `updatedAt` (a `Date.now()` value), ticking once a second in the browser with no request. */
export function useSecondsSince(updatedAt: number | null | undefined): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  if (!updatedAt) return null;
  return Math.max(0, Math.floor((now - updatedAt) / 1000));
}

/**
 * A tab's toolbar line (decision 11): "Updated 4 s ago" on the left (from React Query's `dataUpdatedAt`, ticking with
 * no request and not announced), the tab's links and secondary buttons on the right. No floating links remain.
 */
export function TabToolbar({ updatedAt, children }: { updatedAt?: number | null; children?: ReactNode }) {
  const seconds = useSecondsSince(updatedAt);
  return (
    <div className={s.tabToolbar} data-ui="tab-toolbar">
      <span className={s.updated} aria-live="off">
        {seconds === null ? "" : T.kit.updatedAgo(seconds)}
      </span>
      {children ? <div className={s.toolbarActions}>{children}</div> : null}
    </div>
  );
}
