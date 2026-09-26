"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { authCall } from "@/lib/api";
import {
  canSeeAdmin,
  canSeeAudit,
  canSeeInbox,
  canSeeReports,
} from "@/lib/roles";
import type { Me } from "@/lib/types";
import { Icon, type IconName } from "../ui/Icon";
import ui from "../ui/ui.module.css";
import { useMe } from "./MeContext";
import { NotificationBell } from "./NotificationBell";
import s from "./shell.module.css";

interface NavDef {
  href: string;
  label: string;
  icon: IconName;
  show: (me: Me) => boolean;
}

const NAV: NavDef[] = [
  { href: "/", label: "Dashboard", icon: "dashboard", show: () => true },
  { href: "/inbox", label: "Case Inbox", icon: "inbox", show: canSeeInbox },
  { href: "/search", label: "Search", icon: "search", show: () => true },
  { href: "/alerts", label: "Alerts & Calendar", icon: "calendar", show: () => true },
  { href: "/causelists", label: "Cause Lists", icon: "list", show: () => true },
  { href: "/reports", label: "Reports", icon: "reports", show: canSeeReports },
  { href: "/admin", label: "Administration", icon: "admin", show: canSeeAdmin },
  { href: "/audit", label: "Audit log", icon: "audit", show: canSeeAudit },
];

const TITLES: Record<string, string> = {
  "": "Dashboard",
  inbox: "Case Inbox",
  search: "Search",
  cases: "Cases",
  alerts: "Alerts & Calendar",
  notifications: "Notifications",
  causelists: "Cause Lists",
  reports: "Reports",
  admin: "Administration",
  audit: "Audit log",
  settings: "Settings",
  welcome: "Welcome",
};

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

function Crumb({ pathname }: { pathname: string }) {
  const [first, second] = pathname.split("/").filter(Boolean);
  const title = TITLES[first ?? ""] ?? "Portal";
  if (first === "cases" && second) {
    return (
      <nav aria-label="Breadcrumb" className={s.crumb}>
        <Link href="/search">Cases</Link> <span aria-hidden="true">/</span> <span aria-current="page">Case detail</span>
      </nav>
    );
  }
  return <div className={s.crumb}>{title}</div>;
}

function GlobalSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = q.trim();
    router.push(v ? `/search?q=${encodeURIComponent(v)}` : "/search");
  };
  return (
    <form role="search" onSubmit={submit} className={s.searchBox}>
      <Icon name="search" size={16} />
      <label htmlFor="global-search" className="sr-only">
        Search cases
      </label>
      <input
        id="global-search"
        type="search"
        placeholder="Search by CINO, case number or party name"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        autoComplete="off"
      />
    </form>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { me } = useMe();
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (me.must_confirm_profile && pathname !== "/welcome") router.replace("/welcome");
  }, [me.must_confirm_profile, pathname, router]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const signOut = async () => {
    setSigningOut(true);
    try {
      await authCall("logout", {});
    } catch {
      /* cookies are cleared server-side where possible; go to sign-in regardless */
    }
    window.location.assign("/login");
  };

  const office = me.department && me.department.id !== me.office.id ? `${me.office.name}, ${me.department.name}` : me.office.name;

  return (
    <div className={s.shell}>
      <a href="#main" className="skip-link">
        Skip to main content
      </a>
      {open ? <button type="button" className={s.backdrop} aria-label="Close menu" onClick={() => setOpen(false)} /> : null}
      <nav id="main-nav" aria-label="Main" className={`${s.nav} ${open ? s.navOpen : ""}`}>
        <Link href="/" className={s.brand}>
          <span className={s.brandTitle}>
            Legal Case
            <br />
            Monitoring Portal
          </span>
          <span className={s.brandCaption}>Gauhati High Court</span>
        </Link>
        <ul className={s.navList}>
          {NAV.filter((n) => n.show(me)).map((n) => {
            const active = isActive(pathname, n.href);
            return (
              <li key={n.href}>
                <Link href={n.href} className={`${s.navItem} ${active ? s.navActive : ""}`} aria-current={active ? "page" : undefined}>
                  <Icon name={n.icon} />
                  {n.label}
                </Link>
              </li>
            );
          })}
        </ul>
        <div className={s.userBox}>
          <div className={s.userCaption}>Signed in as</div>
          <div className={s.userName}>{me.full_name}</div>
          <div className={s.userMeta}>
            {me.designation ? (
              <>
                {me.designation}
                <br />
              </>
            ) : null}
            {office}
          </div>
          <div className={s.userActions}>
            <Link href="/settings" className={s.userAction}>
              <Icon name="settings" size={14} />
              Settings
            </Link>
            <button type="button" className={s.userAction} onClick={signOut} disabled={signingOut}>
              <Icon name="logout" size={14} />
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        </div>
      </nav>
      <div className={s.body}>
        <header className={s.header}>
          <button
            type="button"
            className={`${ui.iconButton} ${s.menuButton}`}
            aria-label="Open menu"
            aria-expanded={open}
            aria-controls="main-nav"
            onClick={() => setOpen(true)}
          >
            <Icon name="menu" />
          </button>
          <Crumb pathname={pathname} />
          <GlobalSearch />
          <NotificationBell />
        </header>
        <main id="main" className={s.main} tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
