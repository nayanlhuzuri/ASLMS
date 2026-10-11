"use client";

/**
 * The portal frame (design portal-shell, decisions 12 and 13; Annexure B): the navy sidebar with the portal name,
 * the navigation by functions and, at its foot, the person, the primary membership's designation and office and
 * the list of all memberships; the header with the breadcrumb, the alert bell and the user menu. There is no
 * acting-membership switch: the API picks the membership that holds the function for each action.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { ErrorBanner, Loading } from "@/components/ui";
import { api, session } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type { AlertCounts, Me } from "@/lib/api/types";
import { canAny } from "@/lib/can";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { CASE_READERS, CRUMBS, navFor } from "@/lib/routes";

import s from "./shell.module.css";

export const ALERT_POLL_MS = 2 * 60 * 1000;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  // an entry stays current across its section's tabs (`/data/load` → every `/data/...` page)
  const section = "/" + (href.split("/")[1] ?? "");
  return pathname === section || pathname.startsWith(section + "/");
}

export function Sidebar({ me }: { me: Me }) {
  const pathname = usePathname() ?? "/";
  const entries = navFor(me);
  return (
    <aside className={s.sidebar}>
      <div className={s.brand}>
        <strong>{T.portal}</strong>
        <span>{T.portalLong}</span>
        <span>{T.court}</span>
      </div>
      <nav className={s.nav} aria-label={T.shell.nav}>
        <ul>
          {entries.map((e) => (
            <li key={e.key}>
              <Link href={e.href} aria-current={isActive(pathname, e.href) ? "page" : undefined}>
                {e.label}
              </Link>
            </li>
          ))}
        </ul>
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
  const counts = useQuery({
    queryKey: ["alerts", "counts"],
    queryFn: () => api<AlertCounts>("/alerts/counts"),
    enabled,
    refetchInterval: ALERT_POLL_MS,
  });
  if (!enabled) return null;
  const unread = counts.data?.unread ?? 0;
  return (
    <Link href="/#alerts" className={s.bell} aria-label={T.shell.alerts(unread)}>
      <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
        <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
      </svg>
      <span className={s.count} aria-hidden="true">
        {formatNumber(unread)}
      </span>
    </Link>
  );
}

function UserMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  async function signOut() {
    try {
      await session("logout");
    } finally {
      queryClient.clear();
      router.replace("/login");
    }
  }

  return (
    <div className={s.menu} ref={ref}>
      <button
        type="button"
        className="mono"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={T.shell.userMenu}
        onClick={() => setOpen((v) => !v)}
        style={{ background: "none", border: "1px solid var(--line)", borderRadius: 6, padding: "6px 10px", cursor: "pointer" }}
      >
        {me.user.full_name}
      </button>
      {open ? (
        <ul>
          <li>
            <Link href="/profile" onClick={() => setOpen(false)}>
              {T.shell.profile}
            </Link>
          </li>
          <li>
            <button type="button" onClick={signOut}>
              {T.shell.signOut}
            </button>
          </li>
        </ul>
      ) : null}
    </div>
  );
}

export function Breadcrumb() {
  const pathname = usePathname() ?? "/";
  const parts = pathname.split("/").filter(Boolean);
  const crumbs = [{ href: "/", label: T.dash.title }];
  parts.forEach((part, i) => {
    crumbs.push({ href: "/" + parts.slice(0, i + 1).join("/"), label: CRUMBS[part] ?? decodeURIComponent(part) });
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

export function PortalShell({ children }: { children: ReactNode }) {
  const me = useMe();
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
      <Sidebar me={me.data} />
      <div className={s.main}>
        <header className={s.header}>
          <Breadcrumb />
          <div className={s.tools}>
            <AlertBell me={me.data} />
            <UserMenu me={me.data} />
          </div>
        </header>
        <main id="main" className={s.content}>
          {children}
        </main>
      </div>
    </div>
  );
}
