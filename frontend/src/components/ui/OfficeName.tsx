"use client";

/**
 * An office shown by its name (design portal-names-and-labels, decisions 5 and 34), the one way the portal shows an
 * office: a `name` from the payload wins, otherwise the name comes from `GET /reference/offices` (`useOfficeNames`).
 * The text is the name in the body font, never `mono`; its `title` is the code, with " · Inactive" for an inactive
 * office. While the names load, after a 403, or for a code the map does not hold, the code shows as plain muted text:
 * a name is never invented. A null code shows "—". With `href` the name is a link (the Audit Log narrows by office).
 */
import Link from "next/link";

import { useOfficeNames } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { officeName } from "@/lib/officeNames";

import s from "./officeName.module.css";

export { officeName } from "@/lib/officeNames";

export function OfficeName({ code, name, href }: { code: string | null | undefined; name?: string | null; href?: string }) {
  const names = useOfficeNames();
  if (!code && !name) return <span>—</span>;
  const item = code ? names.data?.get(code) : undefined;
  const text = name || item?.name;
  if (!text) {
    const plain = <span className="muted">{code}</span>;
    return href ? <Link href={href}>{plain}</Link> : plain;
  }
  const title = code ? `${code}${item && !item.is_active ? T.kit.officeInactive : ""}` : undefined;
  const body = (
    <span className={s.name} title={title} data-office-code={code ?? undefined}>
      {text}
    </span>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

/**
 * `officeName` with the names map of `useOfficeNames`, for strings built in a component (`T.inbox.fromTo`,
 * `T.claim.transferFrom`…); null for no code, so a builder keeps its own wording for "none".
 */
export function useOfficeName(): (code: string | null | undefined, name?: string | null) => string | null {
  const names = useOfficeNames();
  return (code, name) => (code || name ? officeName(code, names.data, name) : null);
}
