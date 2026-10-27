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
  OfficePicker,
  Pagination,
  SelectField,
  Tabs,
  TextArea,
  TextField,
  UserPicker,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { labelOf, useLabels, useMe } from "@/lib/api/hooks";
import type { TicketDetail, TicketDocument, TicketList, UserChoice, UserLookup, UserOut } from "@/lib/api/types";
import { can, isSuperAdmin, usersStateWide } from "@/lib/can";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { refPath } from "@/lib/refs";
import { STATUSES, type TicketStatus } from "@/lib/tickets";
import { useAction } from "@/lib/useAction";

import a from "./admin.module.css";

import { DEPARTMENT_TIER } from "./Offices";
import { assignableOptions, PAGE_SIZE, useDesignations } from "./Users";

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
        <DataTable
          caption={T.tickets.documents}
          rows={ticket.documents}
          rowKey={(d) => d.id}
          columns={[
            {
              key: "description",
              header: T.tickets.description,
              primary: true,
              cell: (d) => (
                <>
                  {d.description ?? d.original_filename ?? d.doc_type}
                  {d.archived ? (
                    <>
                      {" "}
                      <Badge>{T.tickets.archived}</Badge>
                    </>
                  ) : null}
                </>
              ),
            },
            { key: "date", header: T.tickets.docDate, cell: (d) => formatDate(d.doc_date) },
            {
              key: "download",
              header: <span className="visually-hidden">{T.tickets.download}</span>,
              label: T.tickets.download,
              cell: (d) => (
                <div className="actions">
                  <a href={`/api/backend${base}/documents/${d.id}/file?disposition=attachment`}>{T.tickets.download}</a>
                  {ticket.can_attach && !d.archived ? (
                    <Button variant="link" onClick={() => setArchiving(d.id)}>
                      {T.tickets.archive}
                    </Button>
                  ) : null}
                </div>
              ),
            },
          ]}
        />
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

type Operation = "set" | "replace" | "end";

/** The incoming head of the request (decision 9): their membership in the department, else their e-mail. */
export function incomingOf(person: UserChoice, department: string, designation: { id: string; name: string } | undefined) {
  const inDept = (person.memberships ?? []).find((m) => m.is_active !== false && m.department_code === department);
  const named = { designation: designation?.name ?? null, designation_id: designation?.id ?? null };
  return inDept ? { membership_id: inDept.id, ...named } : { email: person.email, ...named };
}

/**
 * A head-change proposal: set (no head yet), replace, or end (super admin only); the outgoing head is retyped. Design
 * office-head-picker, decision 9: the department from the Office Picker (fixed to a department admin's own), the
 * incoming head from the User Picker with the designation dropdown, and "Someone From Another Office" (an exact e-mail)
 * for a requester whose view is not State-wide. `department` and `operation` may come from the address.
 */
export function NewTicketForm({ department: initialDepartment, operation: initialOperation }: { department?: string; operation?: string } = {}) {
  const router = useRouter();
  const me = useMe();
  const labels = useLabels();
  const designations = useDesignations();
  const superAdmin = isSuperAdmin(me.data);
  // design office-head-picker-followups, decision 4: the server's rule for listing logins with no office
  const stateWide = usersStateWide(me.data);
  const ownDepartment =
    me.data?.memberships?.find((m) => m.role === "dept_admin" && m.is_active !== false)?.department_code ?? "";
  const [department, setDepartment] = useState((initialDepartment ?? "").trim().toUpperCase());
  const [operation, setOperation] = useState<Operation>(
    initialOperation === "replace" || initialOperation === "end" ? (initialOperation as Operation) : "set",
  );
  const [person, setPerson] = useState<UserChoice | null>(null);
  const [designationId, setDesignationId] = useState("");
  const [otherOpen, setOtherOpen] = useState(false);
  const [otherEmail, setOtherEmail] = useState("");
  const [other, setOther] = useState<UserLookup | null | undefined>(undefined);
  const [roleTo, setRoleTo] = useState("dept_officer");
  const [remark, setRemark] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [docDate, setDocDate] = useState("");
  const save = useAction();
  const check = useAction();
  const fixed = !superAdmin && !!ownDepartment;
  const dept = (fixed ? ownDepartment : department).trim().toUpperCase();
  const officerTypes = assignableOptions(labels.data?.user_types).filter((o) =>
    ["dept_officer", "directorate_user", "standing_counsel", "referral_reviewer"].includes(o.value),
  );
  const heads = useQuery({
    queryKey: ["admin", "users", "heads", dept],
    queryFn: () => api<UserOut[]>("/admin/users", { query: { office: dept, role: "dept_head" } }),
    enabled: !!dept && operation !== "end",
  });
  const currentHeads = new Set((heads.data ?? []).map((h) => h.id));
  const designation = designations.data?.find((d) => d.id === designationId);

  function blocked(u: UserChoice): string | null {
    if (currentHeads.has(u.id)) return T.userPicker.currentHeadNote;
    const inDept = (u.memberships ?? []).find((m) => m.is_active !== false && m.department_code === dept);
    if (!inDept) return null;
    if (inDept.office.code !== dept) return T.userPicker.worksElsewhereNote(inDept.office.code);
    if (inDept.role === "dept_admin" && !superAdmin) return T.userPicker.adminNote;
    return null;
  }

  async function lookUp() {
    setOther(undefined);
    await check.run(async () => {
      try {
        setOther(await api<UserLookup>("/admin/users/lookup", { query: { email: otherEmail.trim() } }));
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) setOther(null);
        else throw err;
      }
    });
  }

  const usingOther = otherOpen && !!other;
  const incomingReady = operation === "end" || ((usingOther || !!person) && !!designationId);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const request: Record<string, unknown> = { operation, department_code: dept, request_remark: remark.trim() || null };
    if (operation !== "end") {
      request.incoming = usingOther
        ? { email: otherEmail.trim(), designation: designation?.name ?? null, designation_id: designation?.id ?? null }
        : person
          ? incomingOf(person, dept, designation)
          : null;
    }
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
        <OfficePicker
          label={T.tickets.department}
          purpose="users"
          kinds={[...DEPARTMENT_TIER]}
          required
          disabled={fixed}
          value={dept || null}
          onChange={(code) => setDepartment(code ?? "")}
        />
        <SelectField
          label={T.tickets.operation}
          value={operation}
          options={operations}
          onChange={(e) => setOperation(e.target.value as Operation)}
        />
      </div>
      {operation !== "end" ? (
        <>
          <div className="row">
            <div className={a.headPerson}>
              <UserPicker
                label={T.tickets.incomingHead}
                required={!usingOther}
                disabled={usingOther}
                includeWithoutOffice={stateWide}
                value={person}
                onChange={setPerson}
                blocked={blocked}
              />
            </div>
            <div className={a.headDesignation}>
              <SelectField
                label={T.offices.headDesignation}
                hint={T.offices.headDesignationHint}
                required
                value={designationId}
                placeholder=""
                options={(designations.data ?? []).map((d) => ({ value: d.id, label: d.name }))}
                onChange={(e) => setDesignationId(e.target.value)}
              />
            </div>
          </div>
          {!stateWide ? (
            otherOpen ? (
              <div className="stack">
                <div className="row">
                  <TextField
                    label={T.tickets.otherOffice}
                    hint={T.tickets.otherOfficeHint}
                    type="email"
                    value={otherEmail}
                    onChange={(e) => {
                      setOtherEmail(e.target.value);
                      setOther(undefined);
                    }}
                  />
                  <Button variant="secondary" busy={check.busy} disabled={!otherEmail.trim()} onClick={() => void lookUp()}>
                    {T.tickets.checkEmail}
                  </Button>
                </div>
                {other ? <p>{T.tickets.otherOfficeFound(other.full_name)}</p> : null}
                {other === null ? <p className="muted">{T.tickets.otherOfficeMissing}</p> : null}
                <ErrorBanner error={check.error} />
              </div>
            ) : (
              <p>
                <Button variant="link" onClick={() => setOtherOpen(true)}>
                  {T.tickets.otherOffice}
                </Button>
              </p>
            )
          ) : null}
        </>
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
        <Button type="submit" busy={save.busy} disabled={!dept || !incomingReady}>
          {T.tickets.submit}
        </Button>
      </div>
    </form>
  );
}
