"use client";

/**
 * One audit entry (design portal-audit-health, decision 6), for deep links an auditor can quote: when, the action,
 * who acted, the case, the record, the IP address and browser, then the before / after table, and links to all
 * entries for the same case, person or record. "Back to the search" goes back when the entry was opened from the
 * search, else to `/audit`. Viewing writes nothing.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { CaseLink, DefinitionList, EmptyState, ErrorBanner, Loading } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import type { AuditRow } from "@/lib/api/types";
import { formatDateTimeSeconds } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString } from "@/lib/params";

import { FROM_SEARCH_KEY } from "./AuditTable";
import { BeforeAfter } from "./BeforeAfter";
import s from "./audit.module.css";

function openedFromSearch(id: string): boolean {
  try {
    return window.sessionStorage.getItem(FROM_SEARCH_KEY) === id;
  } catch {
    return false;
  }
}

export function AuditEntry({ id }: { id: string }) {
  const router = useRouter();
  const entry = useQuery({
    queryKey: ["audit", "entry", id],
    queryFn: () => api<AuditRow>(`/audit/${encodeURIComponent(id)}`),
    retry: (count, error) => !(error instanceof ApiError && error.status >= 400) && count < 2,
  });
  const back = (
    <Link
      href="/audit"
      onClick={(e) => {
        if (openedFromSearch(id)) {
          e.preventDefault();
          router.back();
        }
      }}
    >
      {T.audit.backToSearch}
    </Link>
  );

  if (entry.isPending) return <Loading />;
  const error = entry.error;
  if (error instanceof ApiError && error.status === 403) {
    return (
      <div className="stack">
        <h1>{T.audit.entryTitle}</h1>
        <EmptyState>{T.audit.readersOnly}</EmptyState>
      </div>
    );
  }
  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return (
      <div className="stack">
        <h1>{T.audit.entryTitle}</h1>
        <EmptyState>{T.audit.noEntry}</EmptyState>
        <p>{back}</p>
      </div>
    );
  }
  if (error || !entry.data) return <ErrorBanner error={error} onRetry={() => void entry.refetch()} />;

  const r = entry.data;
  const a = r.actor;
  const by = a.name ? [a.name, a.designation, a.office_code].filter(Boolean).join(", ") : T.audit.system;
  const links: { href: string; label: string }[] = [];
  if (r.case?.ref_no) links.push({ href: "/audit" + queryString({ case: r.case.ref_no }), label: T.audit.entriesForCase });
  if (a.user_id) links.push({ href: "/audit" + queryString({ user: a.user_id }), label: T.audit.entriesByPerson });
  if (r.entity_id) {
    links.push({
      href: "/audit" + queryString({ entity_type: r.entity_type, entity_id: r.entity_id }),
      label: T.audit.entriesForRecord,
    });
  }

  return (
    <div className="stack">
      <h1>{T.audit.entryTitle}</h1>
      <section className="card stack" aria-label={T.audit.entry}>
        <DefinitionList
          items={[
            [T.audit.when, formatDateTimeSeconds(r.at)],
            [T.audit.action, <span key="action" className={s.code}>{r.action}</span>],
            [T.audit.by, by],
            [T.audit.case, r.case?.ref_no ? <CaseLink key="case" value={{ ...r.case, ref_no: r.case.ref_no }} /> : null],
            [
              T.audit.record,
              <span key="record" className={s.code}>
                {r.entity_type}
                {r.entity_id ? ` ${r.entity_id}` : ""}
              </span>,
            ],
            [T.audit.ip, r.ip ? <span key="ip" className="mono">{r.ip}</span> : null],
            [T.audit.browser, r.user_agent],
          ]}
        />
      </section>
      <section className="stack" aria-label={T.audit.beforeAfter}>
        <h2>{T.audit.beforeAfter}</h2>
        <BeforeAfter before={r.before} after={r.after} />
      </section>
      <ul className={s.links}>
        {links.map((l) => (
          <li key={l.label}>
            <Link href={l.href}>{l.label}</Link>
          </li>
        ))}
        <li>{back}</li>
      </ul>
    </div>
  );
}
