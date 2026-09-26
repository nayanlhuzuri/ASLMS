"use client";

import Link from "next/link";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useMe } from "@/components/shell/MeContext";
import { Button } from "@/components/ui/Button";
import { Field, FormRow, Select, TextInput } from "@/components/ui/Field";
import { Card, PageHeader } from "@/components/ui/Layout";
import { Pagination } from "@/components/ui/Pagination";
import { Async, Empty, ErrorState, Loading } from "@/components/ui/States";
import { DataTable } from "@/components/ui/Table";
import { api, errorMessage } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { canSeeAudit } from "@/lib/roles";
import type { Audit, CaseCard, Page, User } from "@/lib/types";
import { useUrlState } from "@/lib/urlState";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function Changes({ before, after }: { before: Record<string, unknown> | null; after: Record<string, unknown> | null }) {
  if (!before && !after) return <span className="muted">-</span>;
  return (
    <details>
      <summary style={{ cursor: "pointer", color: "var(--accent)", fontWeight: 600, fontSize: 13, minHeight: 32 }}>Show</summary>
      <pre style={{ fontFamily: "var(--font-mono)", fontSize: 12, whiteSpace: "pre-wrap", overflowWrap: "anywhere", margin: "6px 0 0", maxWidth: 420, textAlign: "left" }}>
        {before ? `Before: ${JSON.stringify(before, null, 1)}\n` : ""}
        {after ? `After: ${JSON.stringify(after, null, 1)}` : ""}
      </pre>
    </details>
  );
}

function AuditInner() {
  const { me } = useMe();
  const url = useUrlState();
  const users = useApi<Page<User>>("/users", { size: 200 });
  const f = { user_id: url.get("user_id"), case_id: url.get("case_id"), action: url.get("action"), from: url.get("from"), to: url.get("to") };
  const page = Number(url.get("page", "1")) || 1;
  const [draft, setDraft] = useState({ ...f, caseRef: f.case_id });
  const [caseError, setCaseError] = useState<string | null>(null);
  const key = url.params.toString();
  useEffect(() => {
    setDraft({ user_id: url.get("user_id"), case_id: url.get("case_id"), action: url.get("action"), from: url.get("from"), to: url.get("to"), caseRef: url.get("case_id") });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const list = useApi<Page<Audit>>(canSeeAudit(me) ? "/audit" : null, {
    user_id: f.user_id || undefined,
    case_id: f.case_id || undefined,
    action: f.action || undefined,
    from: f.from || undefined,
    to: f.to || undefined,
    page,
    size: 50,
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setCaseError(null);
    let caseId = "";
    const ref = draft.caseRef.trim();
    if (ref) {
      if (UUID.test(ref)) caseId = ref;
      else {
        try {
          const c = await api.get<CaseCard>(`/cases/by-cnr/${encodeURIComponent(ref.toUpperCase())}`);
          caseId = c.id;
        } catch (err) {
          setCaseError(`No case with CNR ${ref.toUpperCase()}: ${errorMessage(err)}`);
          return;
        }
      }
    }
    url.set({ user_id: draft.user_id, case_id: caseId, action: draft.action.trim(), from: draft.from, to: draft.to, page: null });
  };

  if (!canSeeAudit(me)) return <Empty title="The audit log is not available for your role" center />;

  return (
    <>
      <PageHeader title="Audit log" sub="Every change and every document download, with who made it. The log cannot be edited." />
      <Card>
        <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <FormRow>
            <Field label="User">
              <Select value={draft.user_id} onChange={(e) => setDraft({ ...draft, user_id: e.target.value })}>
                <option value="">Anyone</option>
                {(users.data?.items ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name} ({u.email})
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Case (CNR)">
              <TextInput className="mono" value={draft.caseRef} onChange={(e) => setDraft({ ...draft, caseRef: e.target.value })} placeholder="GAHC01..." />
            </Field>
            <Field label="Action" hint="For example case.claim, document.download">
              <TextInput value={draft.action} onChange={(e) => setDraft({ ...draft, action: e.target.value })} />
            </Field>
            <Field label="From">
              <TextInput type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
            </Field>
            <Field label="To">
              <TextInput type="date" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
            </Field>
          </FormRow>
          {caseError ? <ErrorState message={caseError} /> : null}
          <div style={{ display: "flex", gap: 10 }}>
            <Button type="submit" variant="primary" icon="search">
              Filter
            </Button>
            <Button onClick={() => url.set({ user_id: null, case_id: null, action: null, from: null, to: null, page: null })}>Clear</Button>
          </div>
        </form>
      </Card>
      <Async state={list} loadingLabel="Loading the audit log">
        {(p) =>
          p.items.length === 0 ? (
            <Empty title="No audit entries match" center />
          ) : (
            <>
              <DataTable
                caption="Audit log"
                rows={p.items}
                rowKey={(r) => r.id}
                columns={[
                  { key: "when", header: "When", render: (r) => <span style={{ whiteSpace: "nowrap" }}>{fmtDateTime(r.created_at)}</span> },
                  {
                    key: "who",
                    header: "Who",
                    render: (r) => (
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <strong>{r.actor_name ?? "System"}</strong>
                        <span className="muted" style={{ fontSize: 12 }}>
                          {[r.actor_designation, r.actor_office_code].filter(Boolean).join(", ")}
                        </span>
                      </div>
                    ),
                  },
                  { key: "action", header: "Action", mono: true, render: (r) => r.action },
                  { key: "entity", header: "Entity", render: (r) => r.entity_type },
                  { key: "case", header: "Case", render: (r) => (r.case_id ? <Link href={`/cases/${r.case_id}`}>Open case</Link> : "-") },
                  { key: "ip", header: "IP", mono: true, render: (r) => r.ip ?? "-" },
                  { key: "changes", header: "Changes", render: (r) => <Changes before={r.before} after={r.after} /> },
                ]}
              />
              <Pagination page={p.page} size={p.size} total={p.total} onPage={(n) => url.set({ page: n > 1 ? n : null })} noun="entries" />
            </>
          )
        }
      </Async>
    </>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AuditInner />
    </Suspense>
  );
}
