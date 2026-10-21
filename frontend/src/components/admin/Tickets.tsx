"use client";

/**
 * Admin tickets (design portal-shell, decision 15; user-memberships decisions 15-20): the list by status with
 * counts; a head-change proposal (`users.propose_head`); approve or reject (the super admin: the server's
 * `can_approve`), withdraw (the proposer: `can_withdraw`); government orders attached (the API's type check, scan
 * and limit), downloaded and archived. `[ref]` accepts the `-` form of the mail links.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  DataTable,
  EmptyState,
  ErrorBanner,
  Loading,
  Pagination,
  SelectField,
  Table,
  Tabs,
  TextArea,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type { TicketDetail, TicketDocument, TicketList } from "@/lib/api/types";
import { can, isSuperAdmin } from "@/lib/can";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { refPath } from "@/lib/refs";
import { STATUSES, type TicketStatus } from "@/lib/tickets";
import { useAction } from "@/lib/useAction";

import a from "./admin.module.css";

import { assignableOptions, DesignationInput, PAGE_SIZE } from "./Users";


function statusBadge(status: string) {
  const tone = status === "approved" ? "success" : status === "rejected" ? "danger" : status === "open" ? "warning" : undefined;
  return <Badge tone={tone}>{T.tickets.statuses[status as TicketStatus] ?? status}</Badge>;
}

export function TicketsList({ status }: { status: TicketStatus }) {
  const me = useMe();
  const router = useRouter();
  const labels = useLabels();
  const [offset, setOffset] = useState(0);
  const list = useQuery({
    queryKey: ["admin", "tickets", status, offset],
    queryFn: () => api<TicketList>("/admin/tickets", { query: { status, limit: PAGE_SIZE, offset } }),
  });
  return (
    <section className="stack" aria-label={T.tickets.title}>
      <div className={a.groupHead}>
        <h2>
          {T.tickets.title}
          {list.data ? <span className="muted"> · {T.tickets.openCount(formatNumber(list.data.counts.open))}</span> : null}
        </h2>
        {can(me.data, "users.propose_head") || can(me.data, "admin.tickets") ? (
          <Link href="/admin/tickets/new" className="button-link">
            {T.tickets.newTicket}
          </Link>
        ) : null}
      </div>
      <Tabs
        label={T.tickets.status}
        items={STATUSES.map((st) => ({
          href: st === "open" ? "/admin/tickets" : `/admin/tickets?status=${st}`,
          label: T.tickets.statuses[st],
          active: st === status,
        }))}
      />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.tickets.empty}</EmptyState>
        ) : (
          <>
            <DataTable
              caption={T.tickets.title}
              rows={list.data.items}
              rowKey={(t) => t.ref_no}
              rowLabel={(t) => t.ref_no}
              onRowClick={(t) => router.push(`/admin/tickets/${refPath(t.ref_no)}`)}
              columns={[
                {
                  key: "ref",
                  header: T.tickets.ref,
                  primary: true,
                  cell: (t) => (
                    <Link href={`/admin/tickets/${refPath(t.ref_no)}`} className="mono">
                      {t.ref_no}
                    </Link>
                  ),
                },
                {
                  key: "kind",
                  header: T.tickets.kind,
                  cell: (t) => (
                    <>
                      {labelOf(labels.data?.ticket_kinds, t.kind)}
                      {t.operation ? <span className="muted"> · {t.operation}</span> : null}
                    </>
                  ),
                },
                { key: "department", header: T.tickets.department, cell: (t) => <span className="mono">{t.department_code ?? "—"}</span> },
                { key: "target", header: T.tickets.target, cell: (t) => t.target.user_name ?? "—" },
                { key: "by", header: T.tickets.requestedBy, cell: (t) => t.requested_by.name ?? "—" },
                { key: "age", header: T.tickets.age, align: "right", cell: (t) => formatNumber(t.age_days) },
                { key: "status", header: T.tickets.status, width: "var(--lead-w)", cell: (t) => statusBadge(t.status) },
              ]}
            />
            <Pagination offset={offset} limit={PAGE_SIZE} total={list.data.total} onChange={setOffset} />
          </>
        )
      ) : null}
    </section>
  );
}

function DocumentsSection({ ticket, onChanged }: { ticket: TicketDetail; onChanged: () => unknown }) {
  const [file, setFile] = useState<File | null>(null);
  const [docDate, setDocDate] = useState("");
  const [description, setDescription] = useState("");
  const [archiving, setArchiving] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const action = useAction();
  const base = `/admin/tickets/${encodeURIComponent(refPath(ticket.ref_no))}`;

  async function attach(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    if (docDate) form.append("doc_date", docDate);
    if (description.trim()) form.append("description", description.trim());
    const out = await action.run(() => api<TicketDocument>(`${base}/documents`, { method: "POST", body: form }));
    if (out.ok) {
      setFile(null);
      setDescription("");
      setDocDate("");
      await onChanged();
    }
  }

  async function archive(e: FormEvent) {
    e.preventDefault();
    if (!archiving) return;
    const out = await action.run(() =>
      api(`${base}/documents/${archiving}/archive`, { method: "POST", body: { reason: reason.trim() } }),
    );
    if (out.ok) {
      setArchiving(null);
      setReason("");
      await onChanged();
    }
  }

  return (
    <section className="card stack" aria-label={T.tickets.documents}>
      <h2>{T.tickets.documents}</h2>
      {ticket.documents.length === 0 ? (
        <p className="muted">{T.users.noDocuments}</p>
      ) : (
        <Table caption={T.tickets.documents}>
          <thead>
            <tr>
              <th scope="col">{T.tickets.description}</th>
              <th scope="col">{T.tickets.docDate}</th>
              <th scope="col">
                <span className="visually-hidden">{T.tickets.download}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {ticket.documents.map((d) => (
              <tr key={d.id}>
                <td>
                  {d.description ?? d.original_filename ?? d.doc_type}
                  {d.archived ? (
                    <>
                      {" "}
                      <Badge>{T.tickets.archived}</Badge>
                    </>
                  ) : null}
                </td>
                <td>{formatDate(d.doc_date)}</td>
                <td>
                  <div className="actions">
                    <a href={`/api/backend${base}/documents/${d.id}/file?disposition=attachment`}>{T.tickets.download}</a>
                    {ticket.can_attach && !d.archived ? (
                      <Button variant="link" onClick={() => setArchiving(d.id)}>
                        {T.tickets.archive}
                      </Button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {archiving ? (
        <form className="row" onSubmit={archive}>
          <TextField label={T.tickets.archiveReason} required value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button type="submit" variant="secondary" busy={action.busy} disabled={reason.trim().length < 3}>
            {T.tickets.archive}
          </Button>
          <Button variant="secondary" onClick={() => setArchiving(null)}>
            {T.cancel}
          </Button>
        </form>
      ) : null}
      {ticket.can_attach ? (
        <form className="row" onSubmit={attach}>
          <TextField
            label={T.tickets.file}
            type="file"
            accept=".pdf,.doc,.docx,image/*,application/pdf"
            required
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <TextField label={T.tickets.docDate} type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} />
          <TextField label={T.tickets.description} value={description} onChange={(e) => setDescription(e.target.value)} />
          <Button type="submit" variant="secondary" busy={action.busy} disabled={!file}>
            {T.tickets.attach}
          </Button>
        </form>
      ) : null}
      <ErrorBanner error={action.error} />
    </section>
  );
}

export function TicketView({ ticketRef }: { ticketRef: string }) {
  const labels = useLabels();
  const queryClient = useQueryClient();
  const key = ["admin", "ticket", ticketRef];
  const ticket = useQuery({
    queryKey: key,
    queryFn: () => api<TicketDetail>(`/admin/tickets/${encodeURIComponent(ticketRef)}`),
  });
  const [remark, setRemark] = useState("");
  const action = useAction();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin"] });

  if (ticket.isPending) return <Loading />;
  if (ticket.error || !ticket.data) return <ErrorBanner error={ticket.error} onRetry={() => ticket.refetch()} />;
  const t = ticket.data;
  const base = `/admin/tickets/${encodeURIComponent(refPath(t.ref_no))}`;

  async function decide(kind: "approve" | "reject" | "withdraw") {
    const body = kind === "reject" ? { remark: remark.trim() } : { remark: remark.trim() || null };
    const out = await action.run(() => api<TicketDetail>(`${base}/${kind}`, { method: "POST", body }));
    if (out.ok) {
      queryClient.setQueryData(key, out.value);
      setRemark("");
      await refresh();
    }
  }

  return (
    <div className="stack">
      <section className="card stack" aria-label={t.ref_no}>
        <div className={a.groupHead}>
          <h2 className="mono">{t.ref_no}</h2>
          {statusBadge(t.status)}
        </div>
        <dl className="facts">
          <dt>{T.tickets.kind}</dt>
          <dd>
            {labelOf(labels.data?.ticket_kinds, t.kind)}
            {t.operation ? ` · ${t.operation}` : ""}
          </dd>
          <dt>{T.tickets.department}</dt>
          <dd className="mono">{t.department_code ?? "—"}</dd>
          <dt>{T.tickets.target}</dt>
          <dd>
            {t.target.user_name ?? "—"}
            {t.target.designation ? `, ${t.target.designation}` : ""}
            {t.target.role_from || t.target.role_to
              ? ` (${labelOf(labels.data?.user_types, t.target.role_from)} → ${labelOf(labels.data?.user_types, t.target.role_to)})`
              : ""}
          </dd>
          <dt>{T.tickets.requestedBy}</dt>
          <dd>
            {t.requested_by.name ?? "—"}
            {t.requested_by.office_code ? ` (${t.requested_by.office_code})` : ""} · {formatDateTime(t.created_at)}
          </dd>
          {t.request_remark ? (
            <>
              <dt>{T.tickets.remark}</dt>
              <dd>{t.request_remark}</dd>
            </>
          ) : null}
          {t.decided_at ? (
            <>
              <dt>{T.tickets.status}</dt>
              <dd>
                {t.decided_by?.name ?? "—"} · {formatDateTime(t.decided_at)}
                {t.decision_remark ? ` — ${t.decision_remark}` : ""}
              </dd>
            </>
          ) : null}
        </dl>
        {t.can_approve || t.can_withdraw ? (
          <div className="stack">
            <TextArea
              label={t.can_approve ? T.tickets.rejectRemark : T.tickets.remark}
              rows={2}
              value={remark}
              onChange={(e) => setRemark(e.target.value)}
            />
            <div className="actions">
              {t.can_approve ? (
                <>
                  <Button busy={action.busy} onClick={() => decide("approve")}>
                    {T.tickets.approve}
                  </Button>
                  <Button variant="danger" busy={action.busy} disabled={remark.trim().length < 3} onClick={() => decide("reject")}>
                    {T.tickets.reject}
                  </Button>
                </>
              ) : null}
              {t.can_withdraw ? (
                <Button variant="secondary" busy={action.busy} onClick={() => decide("withdraw")}>
                  {T.tickets.withdraw}
                </Button>
              ) : null}
            </div>
          </div>
        ) : null}
        <ErrorBanner error={action.error} />
      </section>
      <DocumentsSection ticket={t} onChanged={() => ticket.refetch()} />
    </div>
  );
}

/** A head-change proposal: set (no head yet), replace, or end (super admin only); the outgoing head is retyped. */
export function NewTicketForm() {
  const router = useRouter();
  const me = useMe();
  const labels = useLabels();
  const superAdmin = isSuperAdmin(me.data);
  const ownDepartment =
    me.data?.memberships?.find((m) => m.role === "dept_admin" && m.is_active !== false)?.department_code ?? "";
  const [department, setDepartment] = useState("");
  const [operation, setOperation] = useState<"set" | "replace" | "end">("set");
  const [email, setEmail] = useState("");
  const [designation, setDesignation] = useState("");
  const [roleTo, setRoleTo] = useState("dept_officer");
  const [remark, setRemark] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [docDate, setDocDate] = useState("");
  const save = useAction();
  const dept = (department || ownDepartment).trim().toUpperCase();
  const officerTypes = assignableOptions(labels.data?.user_types).filter((o) =>
    ["dept_officer", "directorate_user", "standing_counsel", "referral_reviewer"].includes(o.value),
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    const request: Record<string, unknown> = { operation, department_code: dept, request_remark: remark.trim() || null };
    if (operation !== "end") request.incoming = { email: email.trim(), designation: designation.trim() || null };
    if (operation !== "set") request.outgoing = { mode: "retype", role_to: roleTo };
    if (file) request.files = [{ doc_type: "government_order", doc_date: docDate || null }];
    const form = new FormData();
    form.append("request", JSON.stringify(request));
    if (file) form.append("files", file);
    const out = await save.run(() => api<TicketDetail>("/admin/tickets/head-change", { method: "POST", body: form }));
    if (out.ok) router.push(`/admin/tickets/${refPath(out.value.ref_no)}`);
  }

  const operations = [
    { value: "set", label: T.tickets.opSet },
    { value: "replace", label: T.tickets.opReplace },
    ...(superAdmin ? [{ value: "end", label: T.tickets.opEnd }] : []),
  ];

  return (
    <form className="card stack" onSubmit={submit} aria-label={T.tickets.newTicket}>
      <h2>{T.tickets.newTicket}</h2>
      <div className="row">
        <TextField label={T.tickets.department} required value={department || ownDepartment} onChange={(e) => setDepartment(e.target.value)} />
        <SelectField
          label={T.tickets.operation}
          value={operation}
          options={operations}
          onChange={(e) => setOperation(e.target.value as "set" | "replace" | "end")}
        />
      </div>
      {operation !== "end" ? (
        <div className="row">
          <TextField label={T.tickets.incomingEmail} type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <DesignationInput value={designation} onChange={setDesignation} />
        </div>
      ) : null}
      {operation !== "set" ? (
        <SelectField label={T.tickets.outgoingType} value={roleTo} options={officerTypes} onChange={(e) => setRoleTo(e.target.value)} />
      ) : null}
      <TextArea label={T.tickets.remark} rows={2} value={remark} onChange={(e) => setRemark(e.target.value)} />
      <div className="row">
        <TextField
          label={T.tickets.file}
          type="file"
          accept=".pdf,.doc,.docx,image/*,application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <TextField label={T.tickets.docDate} type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} />
      </div>
      <ErrorBanner error={save.error} />
      <div>
        <Button type="submit" busy={save.busy} disabled={!dept}>
          {T.tickets.submit}
        </Button>
      </div>
    </form>
  );
}
