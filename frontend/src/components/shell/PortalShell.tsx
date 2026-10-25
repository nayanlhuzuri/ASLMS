"use client";

/**
 * The portal frame (design portal-shell, decisions 12 and 13; portal-ui-redesign, decisions 4, 18, 21 and 22).
 * The header: the menu button (phones), the emblem slot and the brand, the search box, the alert bell and the avatar
 * menu. The white sidebar: the navigation in its groups (Work, Oversight, Settings) with server counts, and at its
 * foot the person, the primary membership's designation and office and the list of all memberships. Below 820 px
 * the sidebar is a drawer (focus trapped, Escape and the overlay close it) and a bottom bar shows up to three
 * entries plus More. The breadcrumb sits inside each page, in its `PageHeader`. There is no acting-membership switch:
 * the API picks the membership that holds the function for each action.
 * Design portal-ui-polish-2, decisions 14-19: the navigation is a one-level tree (`NavTree`), the same in the drawer.
 */
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

import { cx, ErrorBanner, Loading, Menu, useOverlay } from "@/components/ui";
import { session } from "@/lib/api/client";
import { labelOf, useAlertCounts, useInboxCounts, useLabels, useMe, useMyCounts } from "@/lib/api/hooks";
import type { Me } from "@/lib/api/types";
import { can, canAny } from "@/lib/can";
import { T } from "@/lib/messages";
import { bottomBarFor, CASE_READERS, entryActive, navFor, navGroupsFor, type NavCount } from "@/lib/routes";

import { Brand } from "./Brand";
import { BellIcon, MenuIcon, MoreIcon, NAV_ICONS, SearchIcon } from "./icons";
import { NavTree } from "./NavTree";
import s from "./shell.module.css";

export { Breadcrumb } from "@/components/ui";

const SIDEBAR_ID = "portal-sidebar";

function isActive(pathname: string, href: string): boolean {
  // an entry stays current across its section's tabs (`/data/load` → every `/data/...` page)
  return entryActive({ href }, pathname);
}

/**
 * The server figures of the navigation's pills (decision 4), re-read on window focus and every two minutes like the
 * bell. Only counts the API serves are read; nothing is counted in the browser.
 */
function useNavCounts(me: Me): Partial<Record<NavCount, number>> {
  const alerts = useAlertCounts(canAny(me, CASE_READERS));
  // Case inbox: the Working on figure of `/inbox/mine/counts` (A2; design case-inbox-merge, decision 10); Case claim: the sum over the login's departments of the strong
  // and possible recommendations and the open transfers in (`/inbox/counts`)
  const mine = useMyCounts(can(me, "cases.view_scope"));
  const showsClaim = navFor(me).some((e) => e.key === "claim");
  const inbox = useInboxCounts(null, showsClaim && can(me, "cases.view_scope"), true);
  const blocks = inbox.data?.departments ?? [];
  const claim = inbox.data
    ? blocks.reduce((n, b) => n + (b.recommended_high ?? 0) + (b.recommended_medium ?? 0) + (b.transfers_in_open ?? 0), 0)
    : undefined;
  return { alerts: alerts.data?.unread, inbox: mine.data?.working, claim };
}

/** Below this width the sidebar is a drawer (decision 18). */
const DRAWER_QUERY = "(min-width: 820px)";

/**
 * Review of round 1: when the window grows past 820 px while the drawer is open, the drawer state resets, so the
 * scroll lock and the focus trap do not stay behind on the laptop layout.
 */
function useCloseOnWide(open: boolean, close: () => void) {
  useEffect(() => {
    if (!open || typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(DRAWER_QUERY);
    if (mql.matches) {
      close();
      return;
    }
    const onChange = (e: MediaQueryListEvent) => {
      if (e.matches) close();
    };
    mql.addEventListener?.("change", onChange);
    return () => mql.removeEventListener?.("change", onChange);
  }, [open, close]);
}

export function Sidebar({
  me,
  open = false,
  drawerRef,
  onNavigate,
}: {
  me: Me;
  /** The phone drawer is open. */
  open?: boolean;
  drawerRef?: RefObject<HTMLElement | null>;
  onNavigate?: () => void;
}) {
  const groups = navGroupsFor(me);
  const counts = useNavCounts(me);
  return (
    <aside
      id={SIDEBAR_ID}
      ref={drawerRef}
      className={cx(s.sidebar, open && s.sidebarOpen)}
      aria-label={open ? T.shell.nav : undefined}
      aria-modal={open ? true : undefined}
      role={open ? "dialog" : undefined}
      tabIndex={open ? -1 : undefined}
    >
      <div className={s.drawerTop}>
        <Brand />
        <HeaderSearch me={me} id="drawer-search" onSearch={onNavigate} />
      </div>
      <nav className={s.nav} aria-label={T.shell.nav}>
        <NavTree groups={groups} counts={counts} onNavigate={onNavigate} />
      </nav>
      <MembershipsFoot me={me} />
    </aside>
  );
}

export function MembershipsFoot({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const labels = useLabels();
  const memberships = me.memberships ?? [];
  const primary = memberships.find((m) => m.is_primary) ?? memberships[0];
  return (
    <div className={s.foot}>
      <strong>{me.user.full_name}</strong>
      {primary ? (
        <>
          {primary.designation ? <span>{primary.designation}</span> : null}
          <span>{primary.office.name}</span>
        </>
      ) : (
        <span>{T.shell.noOffice}</span>
      )}
      {memberships.length > 0 ? (
        <>
          <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
            {T.shell.offices(memberships.length)}
          </button>
          {open ? (
            <ul aria-label={T.shell.offices(memberships.length)}>
              {memberships.map((m) => (
                <li key={m.id}>
                  {m.designation ? `${m.designation}, ` : ""}
                  {m.office.name} · {labelOf(labels.data?.user_types, m.role)}
                  {m.is_primary ? ` (${T.shell.primary})` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export function AlertBell({ me }: { me: Me }) {
  const enabled = canAny(me, CASE_READERS);
  // design portal-files-alerts, decision 4: the list is the bell's target; one shared counts query
  const counts = useAlertCounts(enabled);
  if (!enabled) return null;
  const unread = counts.data?.unread ?? 0;
  return (
    <Link href="/alerts" className={s.iconButton} aria-label={T.shell.alerts(unread)}>
      <BellIcon size={20} />
      {unread > 0 ? <span className={s.dot} aria-hidden="true" /> : null}
    </Link>
  );
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase();
}

function UserMenu({ me }: { me: Me }) {
  const router = useRouter();
  const queryClient = useQueryClient();

  async function signOut() {
    try {
      await session("logout");
    } finally {
      queryClient.clear();
      router.replace("/login");
    }
  }

  return (
    <Menu
      label={T.shell.userMenu}
      triggerClassName={s.avatar}
      trigger={
        <span aria-hidden="true" title={me.user.full_name}>
          {initials(me.user.full_name)}
        </span>
      }
      items={[
        { key: "profile", href: "/profile", label: T.shell.profile },
        { key: "signout", label: T.shell.signOut, onSelect: () => void signOut() },
      ]}
    />
  );
}

/**
 * The header search box (design portal-cases, decision 3; Annexure B "Search by CINO, case number or party name"):
 * shown to case readers, it opens `/search?q=…`. On phones it moves into the drawer's top.
 */
export function HeaderSearch({ me, id = "header-search", onSearch }: { me: Me; id?: string; onSearch?: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  if (!canAny(me, CASE_READERS)) return null;
  return (
    <form
      role="search"
      className={s.search}
      onSubmit={(e) => {
        e.preventDefault();
        const text = q.trim();
        router.push(text ? `/search?q=${encodeURIComponent(text)}` : "/search");
        onSearch?.();
      }}
    >
      <label htmlFor={id} className="visually-hidden">
        {T.search.box}
      </label>
      <span className={s.searchIcon}>
        <SearchIcon size={16} />
      </span>
      <input id={id} type="search" placeholder={T.search.box} value={q} onChange={(e) => setQ(e.target.value)} />
      <button type="submit" className="visually-hidden">
        {T.search.go}
      </button>
    </form>
  );
}

/** The phone bottom bar (decision 18): up to three of Dashboard, Case inbox and Files, plus More (the drawer). */
export function BottomBar({ me, onMore, moreOpen }: { me: Me; onMore: () => void; moreOpen?: boolean }) {
  const pathname = usePathname() ?? "/";
  const entries = bottomBarFor(me);
  return (
    <nav className={s.bottomBar} aria-label={T.shell.quickLinks}>
      {entries.map((e) => {
        const Icon = NAV_ICONS[e.key];
        return (
          <Link key={e.key} href={e.href} aria-current={isActive(pathname, e.href) ? "page" : undefined}>
            {Icon ? <Icon /> : null}
            <span>{e.label}</span>
          </Link>
        );
      })}
      <button type="button" aria-expanded={!!moreOpen} aria-controls={SIDEBAR_ID} onClick={onMore}>
        <MoreIcon />
        <span>{T.shell.more}</span>
      </button>
    </nav>
  );
}

export function PortalShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const [drawer, setDrawer] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const closeDrawer = useCallback(() => setDrawer(false), []);
  useOverlay(drawerRef, drawer, closeDrawer);
  useCloseOnWide(drawer, closeDrawer);
  if (me.isPending) return <Loading />;
  if (me.error || !me.data) {
    return (
      <main className={s.content}>
        <ErrorBanner error={me.error} onRetry={() => me.refetch()} />
      </main>
    );
  }
  return (
    <div className={s.frame}>
      <a href="#main" className="skip-link">
        {T.skip}
      </a>
      <header className={s.header}>
        <button
          type="button"
          className={cx(s.iconButton, s.menuButton)}
          aria-label={T.shell.openMenu}
          aria-expanded={drawer}
          aria-controls={SIDEBAR_ID}
          onClick={() => setDrawer(true)}
        >
          <MenuIcon />
        </button>
        <Brand />
        <div className={s.tools}>
          <div className={s.headerSearch}>
            <HeaderSearch me={me.data} />
          </div>
          <AlertBell me={me.data} />
          <UserMenu me={me.data} />
        </div>
      </header>
      <div className={s.body}>
        <Sidebar me={me.data} open={drawer} drawerRef={drawerRef} onNavigate={() => setDrawer(false)} />
        {drawer ? <div className={s.scrim} data-testid="drawer-overlay" onClick={() => setDrawer(false)} /> : null}
        <main id="main" className={s.content}>
          {children}
        </main>
      </div>
      <BottomBar me={me.data} moreOpen={drawer} onMore={() => setDrawer(true)} />
    </div>
  );
}
