"use client";

/**
 * The side menu as a one-level tree (design portal-ui-polish-2, decisions 14-19).
 *
 * - Each group (Work, Oversight, Settings) is one `role="tree"` labelled by its heading. Rows are links with
 *   `role="treeitem"` and `aria-level`; an expanding entry has `aria-expanded` and owns its `role="group"` of children
 *   (the navigation treeview pattern). The active page has `aria-current="page"`.
 * - One open branch at a time. Clicking a closed parent opens it and goes to its landing page unless the person is
 *   already on one of its pages; clicking an open parent closes it without navigating. On every route change the
 *   parent of the active child opens itself.
 * - One roving `tabindex` spans the whole menu: Tab enters once and leaves once. Up and Down move between visible rows
 *   across groups, Home and End go to the first and last, Right opens a closed parent or moves to its first child,
 *   Left closes an open parent or moves from a child to its parent, Enter follows the link.
 * - The children's wrapper animates `grid-template-rows` over `--med` (0 ms under reduced motion, so the branch opens
 *   at once with no JavaScript); a closed branch is `inert` and hidden, so its links are neither focusable nor read.
 * - A truncated label gets the full label as its `title`, measured on pointer enter and focus.
 * Showing an entry is convenience only: every page and API keeps its own check.
 */
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type SyntheticEvent,
} from "react";

import { cx } from "@/components/ui";
import { formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import {
  activeChild,
  childActive,
  entryActive,
  onPath,
  type NavCount,
  type NavEntry,
  type NavGroup,
  type NavLocation,
} from "@/lib/routes";

import { ChevronIcon, NAV_ICONS } from "./icons";
import s from "./shell.module.css";

interface Row {
  id: string;
  level: 1 | 2;
  parent: string | null;
  hasChildren: boolean;
}

/** Sets `title` to the full label only when the label is cut off (decision 18). */
export function titleIfTruncated(e: SyntheticEvent<HTMLElement>): void {
  const el = e.currentTarget;
  const label = el.querySelector<HTMLElement>("[data-nav-label]");
  if (!label) return;
  if (label.scrollWidth > label.clientWidth) el.title = label.textContent ?? "";
  else el.removeAttribute("title");
}

/** The hash of the address, kept in step with `hashchange` (the `/system` sections are anchors). */
function useHash(pathname: string): string {
  const [hash, setHash] = useState("");
  useEffect(() => {
    const read = () => setHash(window.location.hash);
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, [pathname]);
  return hash;
}

export interface NavTreeProps {
  groups: NavGroup[];
  counts: Partial<Record<NavCount, number>>;
  /** A link was chosen (the phone drawer closes); opening or closing a parent does not call it. */
  onNavigate?: () => void;
}

/** The tree, reading the query string inside a Suspense boundary (the layout renders it on every page). */
export function NavTree(props: NavTreeProps) {
  return (
    <Suspense fallback={<NavTreeInner {...props} search="" />}>
      <NavTreeWithSearch {...props} />
    </Suspense>
  );
}

function NavTreeWithSearch(props: NavTreeProps) {
  const search = useSearchParams();
  return <NavTreeInner {...props} search={search?.toString() ?? ""} />;
}

function NavTreeInner({ groups, counts, onNavigate, search }: NavTreeProps & { search: string }) {
  const pathname = usePathname() ?? "/";
  const hash = useHash(pathname);
  const loc: NavLocation = useMemo(() => ({ pathname, hash, search: search ? `?${search}` : "" }), [pathname, hash, search]);
  const parents = useMemo(() => groups.flatMap((g) => g.entries).filter((e) => e.children), [groups]);
  const onPathKey = parents.find((e) => onPath(e, loc))?.key ?? null;
  const [open, setOpen] = useState<string | null>(onPathKey);
  // decision 16: on every route change the parent of the active page opens itself (state adjusted while rendering)
  const routeKey = `${pathname}|${hash}|${search}`;
  const [seenRoute, setSeenRoute] = useState(routeKey);
  if (seenRoute !== routeKey) {
    setSeenRoute(routeKey);
    if (onPathKey) setOpen(onPathKey);
  }

  const rows: Row[] = useMemo(
    () =>
      groups.flatMap((g) =>
        g.entries.flatMap((e) => {
          const own: Row = { id: e.key, level: 1, parent: null, hasChildren: !!e.children };
          if (!e.children || open !== e.key) return [own];
          return [own, ...e.children.map((c): Row => ({ id: `${e.key}/${c.key}`, level: 2, parent: e.key, hasChildren: false }))];
        }),
      ),
    [groups, open],
  );

  const currentId = useMemo(() => {
    for (const g of groups) {
      for (const e of g.entries) {
        const child = activeChild(e, loc);
        if (child && open === e.key) return `${e.key}/${child}`;
        if (!e.children && entryActive(e, pathname)) return e.key;
      }
    }
    return null;
  }, [groups, loc, open, pathname]);

  const [focusId, setFocusId] = useState<string | null>(null);
  const tabStop = rows.some((r) => r.id === focusId) ? focusId : (currentId && rows.some((r) => r.id === currentId) ? currentId : rows[0]?.id);
  const refs = useRef(new Map<string, HTMLAnchorElement>());
  const setRef = useCallback((id: string) => (el: HTMLAnchorElement | null) => {
    if (el) refs.current.set(id, el);
    else refs.current.delete(id);
  }, []);
  const [pendingFocus, setPendingFocus] = useState<string | null>(null);
  useEffect(() => {
    if (!pendingFocus) return;
    const el = refs.current.get(pendingFocus);
    if (el) {
      el.focus();
      setPendingFocus(null);
    }
  }, [pendingFocus, rows]);

  function moveTo(id: string | undefined) {
    if (!id) return;
    setFocusId(id);
    setPendingFocus(id);
  }

  function onKeyDown(e: KeyboardEvent<HTMLElement>) {
    const id = (e.target as HTMLElement).closest<HTMLElement>("[data-row]")?.dataset.row;
    if (!id) return;
    const i = rows.findIndex((r) => r.id === id);
    const row = rows[i];
    if (!row) return;
    let handled = true;
    switch (e.key) {
      case "ArrowDown":
        moveTo(rows[Math.min(i + 1, rows.length - 1)]?.id);
        break;
      case "ArrowUp":
        moveTo(rows[Math.max(i - 1, 0)]?.id);
        break;
      case "Home":
        moveTo(rows[0]?.id);
        break;
      case "End":
        moveTo(rows[rows.length - 1]?.id);
        break;
      case "ArrowRight":
        if (row.hasChildren) {
          if (open !== row.id) setOpen(row.id);
          else moveTo(rows[i + 1]?.parent === row.id ? rows[i + 1]?.id : undefined);
        }
        break;
      case "ArrowLeft":
        if (row.hasChildren && open === row.id) setOpen(null);
        else if (row.parent) moveTo(row.parent);
        break;
      default:
        handled = false;
    }
    if (handled) e.preventDefault();
  }

  function parentClick(entry: NavEntry, e: MouseEvent<HTMLAnchorElement>) {
    setFocusId(entry.key);
    if (open === entry.key) {
      e.preventDefault();
      setOpen(null);
      return;
    }
    setOpen(entry.key);
    // already on one of its pages: open it without going anywhere
    if (onPath(entry, loc)) e.preventDefault();
  }

  return (
    <div className={s.tree} onKeyDown={onKeyDown}>
      {groups.map((g) => (
        <div key={g.key} className={s.group}>
          <div className={s.groupLabel} id={`nav-group-${g.key}`}>
            {g.label}
          </div>
          <ul role="tree" aria-labelledby={`nav-group-${g.key}`}>
            {g.entries.map((entry) => {
              const Icon = NAV_ICONS[entry.key];
              const n = entry.count ? counts[entry.count] : undefined;
              const shown = typeof n === "number" && n > 0;
              const isParent = !!entry.children;
              const isOpen = isParent && open === entry.key;
              const groupId = `nav-children-${entry.key}`;
              const leafCurrent = !isParent && currentId === entry.key;
              const path = isParent && onPath(entry, loc);
              return (
                <li key={entry.key} role="none">
                  <Link
                    href={entry.href}
                    ref={setRef(entry.key)}
                    role="treeitem"
                    aria-level={1}
                    aria-expanded={isParent ? isOpen : undefined}
                    aria-owns={isParent ? groupId : undefined}
                    aria-current={leafCurrent ? "page" : undefined}
                    aria-label={shown ? T.nav.count(entry.label, formatNumber(n)) : entry.label}
                    tabIndex={tabStop === entry.key ? 0 : -1}
                    data-row={entry.key}
                    className={cx(s.row, path && s.onPath)}
                    onFocus={(e) => {
                      setFocusId(entry.key);
                      titleIfTruncated(e);
                    }}
                    onPointerEnter={titleIfTruncated}
                    onClick={(e) => (isParent ? parentClick(entry, e) : onNavigate?.())}
                  >
                    <span className={s.navIcon}>{Icon ? <Icon /> : null}</span>
                    <span className={s.navLabel} data-nav-label="">
                      {entry.label}
                    </span>
                    {shown ? (
                      <span className={s.navCount} aria-hidden="true">
                        {formatNumber(n)}
                      </span>
                    ) : null}
                    {isParent ? (
                      <span className={cx(s.chevron, isOpen && s.chevronOpen)} aria-hidden="true">
                        <ChevronIcon />
                      </span>
                    ) : null}
                  </Link>
                  {isParent ? (
                    <div
                      className={cx(s.children, isOpen && s.childrenOpen)}
                      inert={!isOpen || undefined}
                      aria-hidden={!isOpen || undefined}
                      data-open={isOpen || undefined}
                    >
                      <ul id={groupId} role="group" aria-label={entry.label}>
                        {entry.children!.map((child, index) => {
                          const id = `${entry.key}/${child.key}`;
                          const current = isOpen && currentId === id;
                          return (
                            <li key={child.key} role="none" style={{ "--i": index } as CSSProperties}>
                              <Link
                                href={child.href}
                                ref={setRef(id)}
                                role="treeitem"
                                aria-level={2}
                                aria-current={current ? "page" : undefined}
                                tabIndex={isOpen && tabStop === id ? 0 : -1}
                                data-row={id}
                                className={cx(s.row, s.childRow, childActive(child, loc) && s.childActive)}
                                onFocus={(e) => {
                                  setFocusId(id);
                                  titleIfTruncated(e);
                                }}
                                onPointerEnter={titleIfTruncated}
                                onClick={() => onNavigate?.()}
                              >
                                <span className={s.navIcon} />
                                <span className={s.navLabel} data-nav-label="">
                                  {child.label}
                                </span>
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}
