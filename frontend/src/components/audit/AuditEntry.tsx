"use client";

/**
 * One audit entry (design portal-audit-health, decision 6), for deep links an auditor can quote: when, the action,
 * who acted, the case, the record, the IP address and browser, then the before / after table, and links to all
 * entries for the same case, person or record. "Back to the search" goes back when the entry was opened from the
 * search, else to `/audit`. Viewing writes nothing.
 * Design portal-screen-fixes-oversight, decision 9: Record shows the record type in words and the `ref_no` the entry's
 * after or before values hold; the raw record id is never drawn, and stays as the value's title, in "All Entries for
 * This Record" and behind "Copy Record ID". "By" shows the office by name (kit `OfficeName`).
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { CaseLink, CopyButton, DefinitionList, EmptyState, ErrorBanner, Loading, OfficeName, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import type { AuditRow } from "@/lib/api/types";
import { actionName } from "@/lib/audit";
import { labelFor } from "@/lib/displayLabels";
import { formatDateTimeSeconds } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString } from "@/lib/params";

import { FROM_SEARCH_KEY } from "./AuditTable";
import { BeforeAfter } from "./BeforeAfter";
import s from "./audit.module.css";

/** The reference readers know: a string `ref_no` in the entry's after values, else its before values. */
export function recordRef(r: Pick<AuditRow, "before" | "after">): string | null {
  for (const values of [r.after, r.before]) {
    const ref = values && typeof values === "object" ? (values as Record<string, unknown>).ref_no : undefined;
    if (typeof ref === "string" && ref) return ref;
  }
  return null;
}

/** Decision 9: the record type in words (an unlabelled code in Title Case), then its reference in the body font. */
function RecordValue({ r }: { r: AuditRow }) {
  const ref = recordRef(r);
  const words = [labelFor({}, r.entity_type), ref].filter(Boolean).join(" ");
  return (
    <span className={s.recordValue}>
      <span title={r.entity_id ?? undefined} data-record="">
        {words}
      </span>
      {/* the normal 36 px size: it stands in a facts list, outside any row */}
      {r.entity_id ? <CopyButton text={r.entity_id} label={T.audit.copyRecordId} size="md" /> : null}
    </span>
  );
}

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
        <PageHeader title={T.audit.entryTitle} />
        <EmptyState>{T.audit.readersOnly}</EmptyState>
      </div>
    );
  }
  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return (
      <div className="stack">
        <PageHeader title={T.audit.entryTitle} />
        <EmptyState>{T.audit.noEntry}</EmptyState>
        <p>{back}</p>
      </div>
    );
  }
  if (error || !entry.data) return <ErrorBanner error={error} onRetry={() => void entry.refetch()} />;

  const r = entry.data;
  const a = r.actor;
  const by = a.name ? (
    <span key="by">
      {[a.name, a.designation].filter(Boolean).join(", ")}
      {a.office_code ? (
        <>
          {", "}
          <OfficeName code={a.office_code} />
        </>
      ) : null}
    </span>
  ) : (
    T.audit.system
  );
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
      <PageHeader title={T.audit.entryTitle} />
      <section className="card stack" aria-label={T.audit.entry}>
        <DefinitionList
          items={[
            [T.audit.when, formatDateTimeSeconds(r.at)],
            [
              T.audit.action,
              // decision 20: the name, then the code an auditor quotes in mono muted text; a code with no name shows itself
              actionName(r.action) === r.action ? (
                <span key="action" className={s.code}>
                  {r.action}
                </span>
              ) : (
                <span key="action">
                  {actionName(r.action)}
                  <span className="muted">
                    {" · "}
                    <code className={s.code}>{r.action}</code>
                  </span>
                </span>
              ),
            ],
            [T.audit.by, by],
            [T.audit.case, r.case?.ref_no ? <CaseLink key="case" value={{ ...r.case, ref_no: r.case.ref_no }} /> : null],
            [T.audit.record, <RecordValue key="record" r={r} />],
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
