"use client";

/**
 * Insights Groups (design state-insights, decisions 14 to 16 and 34) on the Settings template, shown only to the Super
 * Administrator (the reserved function `admin.insights_groups`; the API refuses everyone else). Two tabs, Subject Groups
 * and Kinds of Case, each its own address (`?tab=family`):
 * - the groups: add, rename, reorder, turn off (a reserved group is marked and can only be renamed or reordered);
 * - the court's categories or case types with code, the court's label, cases, pending and a group select, with Search
 *   and a Not Grouped filter, saved in one batch with a toast (one audit row per changed line, by the API).
 * A change takes effect at once: the grouping is read when Insights counts, with no rebuild.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  type Column,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorBanner,
  ListSearch,
  ListToolbar,
  Loading,
  numCell,
  SelectField,
  Tabs,
  TextField,
  useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import type { InsightCaseType, InsightCategory, InsightGroup } from "@/lib/api/types";
import { formatNumber } from "@/lib/format";
import { matchesWords } from "@/lib/listSearch";
import { GROUPS_ERRORS, T } from "@/lib/messages";
import type { Params } from "@/lib/params";
import { useAction } from "@/lib/useAction";

import s from "./insightsGroups.module.css";
import { SwitchLine } from "./mapping/common";

const G = T.insightsGroups;
export type GroupKind = "subject" | "family";
const KEY = ["admin", "insights-groups"] as const;

export function tabOf(params: Params): GroupKind {
  return params.tab === "family" ? "family" : "subject";
}

/** One member line, whichever the tab: a category (by code) or a case type (by id). */
interface Member {
  key: string;
  code: number;
  label: string;
  group: string | null;
  cases: number;
  pending: number;
}

function categoryMember(c: InsightCategory): Member {
  return { key: String(c.code), code: c.code, label: c.label, group: c.group ?? null, cases: c.cases, pending: c.pending };
}

function caseTypeMember(c: InsightCaseType): Member {
  return { key: c.id, code: c.code, label: c.full_name ? `${c.name} (${c.full_name})` : c.name, group: c.group, cases: c.cases, pending: c.pending };
}

/** The changed lines of a batch, as the API takes them (`null`: Not Grouped, or Other for a case type). */
export function changesOf(kind: GroupKind, edits: Record<string, string>, members: readonly Member[]) {
  const out: { key: string; group: string | null }[] = [];
  for (const m of members) {
    if (!(m.key in edits)) continue;
    const next = edits[m.key] === "" ? null : edits[m.key]!;
    if (next !== m.group) out.push({ key: m.key, group: next });
  }
  return kind === "subject"
    ? { changes: out.map((c) => ({ code: Number(c.key), group: c.group })) }
    : { changes: out.map((c) => ({ case_type_id: c.key, group: c.group })) };
}

export function InsightsGroups({ params }: { params: Params }) {
  const kind = tabOf(params);
  return (
    <section className="stack" aria-label={G.title}>
      <h2>{G.title}</h2>
      <p className="muted">{G.intro}</p>
      <Tabs
        label={G.tabsLabel}
        items={(["subject", "family"] as const).map((k) => ({
          href: k === "subject" ? "/admin/insights-groups" : "/admin/insights-groups?tab=family",
          label: G.tabs[k]!,
          active: k === kind,
        }))}
      />
      <GroupsTab key={kind} kind={kind} />
    </section>
  );
}

function GroupsTab({ kind }: { kind: GroupKind }) {
  const groups = useQuery({
    queryKey: [...KEY, "groups", kind],
    queryFn: () => api<InsightGroup[]>("/admin/insights/groups", { query: { kind } }),
  });
  const forbidden = groups.error instanceof ApiError && groups.error.status === 403;
  if (forbidden) return <EmptyState>{G.notAllowedNote}</EmptyState>;
  return (
    <>
      <GroupList kind={kind} groups={groups.data} pending={groups.isPending} error={groups.error} onRetry={() => void groups.refetch()} />
      {groups.data ? <MemberList kind={kind} groups={groups.data} /> : null}
    </>
  );
}

function GroupList({
  kind,
  groups,
  pending,
  error,
  onRetry,
}: {
  kind: GroupKind;
  groups: InsightGroup[] | undefined;
  pending: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState<InsightGroup | null>(null);
  const [turning, setTurning] = useState<InsightGroup | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEY });
  const columns: Column<InsightGroup>[] = [
    { key: "label", header: G.cols.name, primary: true, rowHeader: true, cell: (g) => g.label },
    { key: "code", header: G.cols.code, cell: (g) => <span className="mono">{g.code}</span> },
    { key: "order", header: G.cols.order, align: "right", cell: (g) => <span className={numCell}>{formatNumber(g.sort_order)}</span> },
    { key: "lines", header: G.cols.lines, align: "right", cell: (g) => <span className={numCell}>{formatNumber(g.members)}</span> },
    { key: "cases", header: G.cols.cases, align: "right", cell: (g) => <span className={numCell}>{formatNumber(g.cases)}</span> },
    { key: "pending", header: G.cols.pending, align: "right", cell: (g) => <span className={numCell}>{formatNumber(g.pending)}</span> },
    {
      key: "status",
      header: G.cols.status,
      cell: (g) => (
        <span className={s.badges}>
          {g.is_active ? <Badge tone="success">{G.activeBadge}</Badge> : <Badge>{G.inactiveBadge}</Badge>}
          {g.is_reserved ? <Badge tone="info">{G.reservedBadge}</Badge> : null}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="visually-hidden">{G.cols.actions}</span>,
      label: G.cols.actions,
      actions: true,
      align: "right",
      cell: (g) => (
        <span className={s.badges}>
          <Button variant="ghost" size="sm" aria-label={G.editTitle(g.label)} onClick={() => setEditing(g)}>
            {G.editButton}
          </Button>
          {g.is_reserved ? null : (
            <Button variant="ghost" size="sm" onClick={() => setTurning(g)}>
              {g.is_active ? G.turnOffButton : G.turnOnButton}
            </Button>
          )}
        </span>
      ),
    },
  ];
  return (
    <section className="stack" aria-labelledby={`groups-${kind}`}>
      <h3 id={`groups-${kind}`}>{G.groupsHeading}</h3>
      <p className="muted">{G.reservedNote}</p>
      {pending ? <Loading /> : null}
      <ErrorBanner error={error} onRetry={onRetry} />
      {groups ? <DataTable caption={G.groupsHeading} rows={groups} rowKey={(g) => g.id} columns={columns} /> : null}
      <AddGroup
        kind={kind}
        onSaved={() => {
          toast(G.groupSavedNote);
          void refresh();
        }}
      />
      {editing ? (
        <EditGroup
          group={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            toast(G.groupSavedNote);
            void refresh();
          }}
        />
      ) : null}
      {turning ? (
        <TurnGroup
          group={turning}
          onClose={() => setTurning(null)}
          onSaved={() => {
            setTurning(null);
            toast(G.groupSavedNote);
            void refresh();
          }}
        />
      ) : null}
    </section>
  );
}

function AddGroup({ kind, onSaved }: { kind: GroupKind; onSaved: () => void }) {
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [order, setOrder] = useState("");
  const action = useAction();
  async function add(e: FormEvent) {
    e.preventDefault();
    const out = await action.run(() =>
      api<InsightGroup>("/admin/insights/groups", {
        method: "POST",
        body: { kind, code: code.trim(), label: label.trim(), ...(order.trim() ? { sort_order: Number(order) } : {}) },
      }),
    );
    if (out.ok) {
      setCode("");
      setLabel("");
      setOrder("");
      onSaved();
    }
  }
  return (
    <>
    <form className={s.addRow} onSubmit={add} aria-label={G.addHeading}>
      <TextField label={G.codeLabel} hint={G.codeHint} required maxLength={40} pattern="[a-z0-9_]{2,40}" value={code} onChange={(e) => setCode(e.target.value)} />
      <TextField label={G.nameLabel} required maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} />
      <TextField label={G.orderLabel} type="number" min={0} max={10000} step={1} value={order} onChange={(e) => setOrder(e.target.value)} />
      <Button type="submit" variant="secondary" busy={action.busy} disabled={!code.trim() || !label.trim()}>
        {G.addButton}
      </Button>
    </form>
    <ErrorBanner error={action.error} messages={GROUPS_ERRORS} />
    </>
  );
}

function EditGroup({ group, onClose, onSaved }: { group: InsightGroup; onClose: () => void; onSaved: () => void }) {
  const [label, setLabel] = useState(group.label);
  const [order, setOrder] = useState(String(group.sort_order));
  const action = useAction();
  async function save() {
    const body: Record<string, unknown> = {};
    if (label.trim() !== group.label) body.label = label.trim();
    if (order.trim() !== "" && Number(order) !== group.sort_order) body.sort_order = Number(order);
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    const out = await action.run(() => api<InsightGroup>(`/admin/insights/groups/${group.id}`, { method: "PATCH", body }));
    if (out.ok) onSaved();
  }
  return (
    <ConfirmDialog
      open
      title={G.editTitle(group.label)}
      confirmLabel={G.saveGroupButton}
      busy={action.busy}
      error={action.error}
      messages={GROUPS_ERRORS}
      onConfirm={() => void save()}
      onClose={onClose}
    >
      <TextField label={G.nameLabel} required maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} />
      <TextField label={G.orderLabel} type="number" min={0} max={10000} step={1} value={order} onChange={(e) => setOrder(e.target.value)} />
    </ConfirmDialog>
  );
}

function TurnGroup({ group, onClose, onSaved }: { group: InsightGroup; onClose: () => void; onSaved: () => void }) {
  const action = useAction();
  const on = !group.is_active;
  async function save() {
    const out = await action.run(() =>
      api<InsightGroup>(`/admin/insights/groups/${group.id}`, { method: "PATCH", body: { is_active: on } }),
    );
    if (out.ok) onSaved();
  }
  return (
    <ConfirmDialog
      open
      title={`${on ? G.turnOnButton : G.turnOffButton}: ${group.label}`}
      confirmLabel={on ? G.turnOnButton : G.turnOffButton}
      busy={action.busy}
      error={action.error}
      messages={GROUPS_ERRORS}
      onConfirm={() => void save()}
      onClose={onClose}
    >
      <p>{G.reservedNote}</p>
    </ConfirmDialog>
  );
}

function MemberList({ kind, groups }: { kind: GroupKind; groups: InsightGroup[] }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const path = kind === "subject" ? "/admin/insights/categories" : "/admin/insights/case-types";
  const members = useQuery({
    queryKey: [...KEY, "members", kind],
    queryFn: async (): Promise<Member[]> =>
      kind === "subject"
        ? (await api<InsightCategory[]>(path)).map(categoryMember)
        : (await api<InsightCaseType[]>(path)).map(caseTypeMember),
  });
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [q, setQ] = useState("");
  const [notGrouped, setNotGrouped] = useState(false);
  const action = useAction();
  const all = members.data ?? [];
  const body = changesOf(kind, edits, all);
  const unsaved = body.changes.length;
  const noneLabel = kind === "subject" ? G.notGroupedLabel : G.otherKindLabel;
  const valueOf = (m: Member) => (m.key in edits ? edits[m.key]! : (m.group ?? ""));
  const inactiveOf = new Set(groups.filter((g) => !g.is_active).map((g) => g.code));
  const ungrouped = (m: Member) => {
    const v = valueOf(m);
    return kind === "subject" ? v === "" || inactiveOf.has(v) : v === "" || v === "other" || inactiveOf.has(v);
  };
  const rows = all.filter((m) => (!notGrouped || ungrouped(m)) && matchesWords(q, String(m.code), m.label));
  const options = (m: Member) => [
    ...(kind === "subject" ? [{ value: "", label: noneLabel }] : []),
    ...groups.filter((g) => g.is_active || g.code === valueOf(m)).map((g) => ({ value: g.code, label: g.label })),
  ];

  async function save() {
    const out = await action.run(() => api<unknown[]>(path, { method: "PUT", body }));
    if (out.ok) {
      toast(G.savedNote(unsaved));
      setEdits({});
      void queryClient.invalidateQueries({ queryKey: KEY });
    }
  }

  const columns: Column<Member>[] = [
    { key: "code", header: G.cols.code, cell: (m) => <span className="mono">{m.code}</span> },
    { key: "label", header: kind === "subject" ? G.cols.label : G.cols.caseType, primary: true, rowHeader: true, cell: (m) => m.label },
    { key: "cases", header: G.cols.cases, align: "right", cell: (m) => <span className={numCell}>{formatNumber(m.cases)}</span> },
    { key: "pending", header: G.cols.pending, align: "right", cell: (m) => <span className={numCell}>{formatNumber(m.pending)}</span> },
    {
      key: "group",
      header: G.cols.group,
      cell: (m) => (
        <SelectField
          label={G.groupFor(m.label)}
          hideLabel
          options={options(m)}
          value={valueOf(m)}
          onChange={(e) => setEdits((prev) => ({ ...prev, [m.key]: e.target.value }))}
        />
      ),
    },
  ];
  const heading = kind === "subject" ? G.categoriesHeading : G.caseTypesHeading;
  return (
    <section className="stack" aria-labelledby={`members-${kind}`}>
      <h3 id={`members-${kind}`}>{heading}</h3>
      <ListToolbar search={<ListSearch label={G.searchLabel} placeholder={G.searchPlaceholder} value={q} onChange={setQ} />}>
        <SwitchLine label={G.notGroupedOnlyLabel} checked={notGrouped} onChange={setNotGrouped} />
      </ListToolbar>
      {members.isPending ? <Loading /> : null}
      <ErrorBanner error={members.error} onRetry={() => void members.refetch()} />
      {members.data ? (
        rows.length === 0 ? (
          <EmptyState compact>{G.emptyNote}</EmptyState>
        ) : (
          <DataTable caption={heading} rows={rows} rowKey={(m) => m.key} columns={columns} />
        )
      ) : null}
      <div className={s.saveLine}>
        {unsaved > 0 ? <span className="muted">{G.unsavedNote(unsaved)}</span> : null}
        <Button variant="primary" busy={action.busy} disabled={unsaved === 0} onClick={() => void save()}>
          {G.saveButton}
        </Button>
      </div>
      <ErrorBanner error={action.error} messages={GROUPS_ERRORS} />
    </section>
  );
}
