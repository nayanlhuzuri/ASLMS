"use client";

/**
 * Counsel codes (design portal-mapping, decision 5; plan §4.1: "each code is mapped to its department in the
 * administration module"; Annexure B "Department mapping"), with the panel of codes seen in cause lists but not
 * mapped. Nothing is mapped automatically: "Map" only fills the form. A code mapped to the root office is generic
 * (recognised, recommends no department); the form sends `is_generic_state` exactly when the root office is chosen.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  CheckField,
  ConfirmDialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  DataTable,
  TextArea,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { MAPPING_KEY, useMe } from "@/lib/api/hooks";
import type { CounselCode, CounselCodeList, UnmappedCode } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { given, isRootOffice, weightBody } from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import {
  conflictAware,
  OfficeCell,
  OfficeFilter,
  OfficePicker,
  RuleStatusActions,
  SearchLink,
  useOfficeChoices,
  WeightCell,
  weightDraft,
  WeightField,
  type WeightDraft,
} from "./common";
import s from "./mapping.module.css";

const CODES_KEY = [...MAPPING_KEY, "codes"] as const;
const UNMAPPED_KEY = [...MAPPING_KEY, "unmapped"] as const;

export function CounselCodes() {
  const me = useMe();
  const canScore = can(me.data, "admin.scoring");
  const choices = useOfficeChoices();
  const queryClient = useQueryClient();
  const officeFieldId = useId();

  const [filter, setFilter] = useState({ q: "", office: "", inactive: false });
  const [qDraft, setQDraft] = useState("");
  const list = useQuery({
    queryKey: [...CODES_KEY, filter],
    queryFn: () =>
      api<CounselCodeList>("/admin/counsel-codes", {
        query: { q: filter.q || undefined, office: filter.office || undefined, include_inactive: filter.inactive || undefined },
      }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: CODES_KEY });

  const [draft, setDraft] = useState({ code: "", office: "", notes: "" });
  const [weight, setWeight] = useState<WeightDraft>(weightDraft(null));
  const [notice, setNotice] = useState<string | null>(null);
  const action = useAction();
  const chosen = choices.offices.find((o) => o.code === draft.office);
  const generic = isRootOffice(chosen);
  const [editing, setEditing] = useState<CounselCode | null>(null);

  async function add(e: FormEvent) {
    e.preventDefault();
    setNotice(null);
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<CounselCode>("/admin/counsel-codes", {
            method: "POST",
            body: {
              code: draft.code.trim(),
              office_code: draft.office.trim(),
              is_generic_state: generic,
              notes: draft.notes.trim() || null,
              ...(canScore ? weightBody(weight.changed, weight.value) : {}),
            },
          }),
        () => void refresh(),
      ),
    );
    if (out.ok) {
      setNotice(T.mapping.appliesWithin(out.value.applies_within_minutes ?? 15));
      setDraft({ code: "", office: "", notes: "" });
      setWeight(weightDraft(null));
      // the mapped code leaves the unmapped panel without scanning the cause lists again
      queryClient.setQueryData<UnmappedCode[]>(UNMAPPED_KEY, (old) => old?.filter((u) => u.code !== out.value.code));
      await refresh();
    }
  }

  function mapCode(code: string) {
    setDraft((d) => ({ ...d, code }));
    document.getElementById(officeFieldId)?.focus();
  }

  const editableGeneric = !!choices.root;

  return (
    <section className="stack" aria-label={T.mapping.codes}>
      <h3>{T.mapping.codes}</h3>
      <form className={`row ${s.form}`} onSubmit={add} aria-label={T.mapping.addCode}>
        <TextField
          label={T.mapping.code}
          required
          maxLength={60}
          hint={T.mapping.codeHint}
          value={draft.code}
          onChange={(e) => setDraft({ ...draft, code: e.target.value })}
        />
        <OfficePicker
          id={officeFieldId}
          choices={choices}
          required
          value={draft.office}
          onChange={(office) => setDraft({ ...draft, office })}
          hint={generic ? T.mapping.genericLine : undefined}
        />
        <TextArea
          label={T.mapping.notes}
          maxLength={4000}
          rows={2}
          value={draft.notes}
          onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
        />
        {canScore ? <WeightField mode="create" draft={weight} onChange={setWeight} /> : null}
        <Button type="submit" busy={action.busy}>
          {T.mapping.addCode}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
      {notice ? <Notice>{notice}</Notice> : null}

      <form
        className="row"
        onSubmit={(e) => {
          e.preventDefault();
          setFilter({ ...filter, q: qDraft.trim() });
        }}
      >
        <TextField label={T.mapping.filterCode} value={qDraft} onChange={(e) => setQDraft(e.target.value)} />
        <OfficeFilter choices={choices} value={filter.office} onChange={(office) => setFilter({ ...filter, office })} />
        <Button type="submit" variant="secondary">
          {T.mapping.apply}
        </Button>
        <CheckField
          inline
          label={T.mapping.includeInactive}
          checked={filter.inactive}
          onChange={(e) => setFilter({ ...filter, inactive: e.target.checked })}
        />
      </form>

      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.mapping.empty}</EmptyState>
        ) : (
          <DataTable
            caption={T.mapping.codes}
            rows={list.data.items}
            rowKey={(row) => row.id}
            columns={[
              { key: "code", header: T.mapping.code, primary: true, cell: (row) => <span className="mono">{row.code}</span> },
              { key: "office", header: T.mapping.office, cell: (row) => <OfficeCell office={row.office} /> },
              {
                key: "weight",
                header: T.mapping.effectiveWeight,
                align: "right",
                cell: (row) => <WeightCell effective={row.effective_weight} override={row.weight_override} />,
              },
              { key: "generic", header: T.mapping.generic, cell: (row) => (row.is_generic_state ? T.yes : "—") },
              {
                key: "status",
                header: T.mapping.status,
                width: "var(--lead-w)",
                cell: (row) => (row.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>),
              },
              { key: "notes", header: T.mapping.notes, cell: (row) => row.notes ?? "—" },
              { key: "updated", header: T.mapping.updated, cell: (row) => formatDateTime(row.updated_at) },
              {
                key: "actions",
                header: T.mapping.actions,
                cell: (row) =>
                  !row.is_generic_state || editableGeneric ? (
                    <div className="actions">
                      <Button variant="link" aria-label={`${T.edit} ${row.code}`} onClick={() => setEditing(row)}>
                        {T.edit}
                      </Button>
                      <RuleStatusActions<CounselCode>
                        path={`/admin/counsel-codes/${row.id}`}
                        active={row.is_active}
                        label={row.code}
                        confirmText={T.mapping.ruleConfirm}
                        onDone={(r) => {
                          setNotice(T.mapping.appliesWithin(r.applies_within_minutes ?? 15));
                          void refresh();
                        }}
                        onConflict={() => void refresh()}
                      />
                    </div>
                  ) : null,
              },
            ]}
          />
        )
      ) : null}

      {editing ? (
        <EditCode
          row={editing}
          canScore={canScore}
          onClose={() => setEditing(null)}
          onSaved={(r) => {
            setEditing(null);
            setNotice(T.mapping.appliesWithin(r.applies_within_minutes ?? 15));
            void refresh();
          }}
          onConflict={() => void refresh()}
        />
      ) : null}

      <UnmappedCodes onMap={mapCode} />
    </section>
  );
}

function EditCode({
  row,
  canScore,
  onClose,
  onSaved,
  onConflict,
}: {
  row: CounselCode;
  canScore: boolean;
  onClose: () => void;
  onSaved: (row: CounselCode) => void;
  onConflict: () => void;
}) {
  const choices = useOfficeChoices();
  const officeId = useId();
  const [office, setOffice] = useState(row.office.code);
  const [notes, setNotes] = useState(row.notes ?? "");
  const [weight, setWeight] = useState<WeightDraft>(weightDraft(row.weight_override));
  const action = useAction();

  async function save() {
    const body: Record<string, unknown> = {
      ...(office.trim() && office.trim() !== row.office.code ? { office_code: office.trim() } : {}),
      ...(notes !== (row.notes ?? "") ? { notes } : {}),
      ...(canScore ? weightBody(weight.changed, weight.value) : {}),
    };
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    const out = await action.run(() =>
      conflictAware(() => api<CounselCode>(`/admin/counsel-codes/${row.id}`, { method: "PATCH", body }), onConflict),
    );
    if (out.ok) onSaved(out.value);
  }

  return (
    <ConfirmDialog
      open
      title={T.mapping.editCode(row.code)}
      onClose={onClose}
      onConfirm={() => void save()}
      busy={action.busy}
      error={given(action.error)}
      confirmLabel={T.save}
    >
      {row.is_generic_state ? <p className="muted">{T.mapping.genericLine}</p> : null}
      <OfficePicker id={officeId} choices={choices} required value={office} onChange={setOffice} />
      <TextArea label={T.mapping.notes} maxLength={4000} rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      {canScore ? <WeightField mode="edit" draft={weight} onChange={setWeight} current={row.weight_override} /> : null}
    </ConfirmDialog>
  );
}

/**
 * Codes seen in cause lists and dossiers with no mapping (`GET /admin/counsel-codes/unmapped?limit=100`), read when
 * the panel is first opened, never on page load (the query scans every cause-list entry).
 */
export function UnmappedCodes({ onMap }: { onMap: (code: string) => void }) {
  const [open, setOpen] = useState(false);
  const list = useQuery({
    queryKey: UNMAPPED_KEY,
    queryFn: () => api<UnmappedCode[]>("/admin/counsel-codes/unmapped", { query: { limit: 100 } }),
    enabled: open,
    staleTime: 10 * 60_000,
    retry: false,
  });
  return (
    <section className={`stack ${s.panel}`} aria-label={T.mapping.unmapped}>
      <div className="row">
        <h3>{T.mapping.unmapped}</h3>
        <Button variant="secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? T.mapping.hideUnmapped : T.mapping.showUnmapped}
        </Button>
      </div>
      {open ? (
        <>
          <Notice>{T.mapping.unmappedNotice}</Notice>
          {list.isFetching && !list.data ? <Loading /> : null}
          <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
          {list.data ? (
            list.data.length === 0 ? (
              <EmptyState>{T.mapping.noUnmapped}</EmptyState>
            ) : (
              <DataTable
                caption={T.mapping.unmapped}
                rows={list.data}
                rowKey={(u) => u.code}
                columns={[
                  { key: "code", header: T.mapping.code, primary: true, cell: (u) => <span className="mono">{u.code}</span> },
                  { key: "entries", header: T.mapping.entries, align: "right", cell: (u) => formatNumber(u.entries) },
                  { key: "last", header: T.mapping.lastListed, cell: (u) => formatDate(u.last_listed) },
                  { key: "example", header: T.mapping.example, cell: (u) => (u.example_case_ref ? <SearchLink ref_no={u.example_case_ref} /> : "—") },
                  {
                    key: "actions",
                    header: T.mapping.actions,
                    cell: (u) => (
                      <Button variant="link" aria-label={T.mapping.mapCode(u.code)} onClick={() => onMap(u.code)}>
                        {T.mapping.map}
                      </Button>
                    ),
                  },
                ]}
              />
            )
          ) : null}
        </>
      ) : null}
    </section>
  );
}
