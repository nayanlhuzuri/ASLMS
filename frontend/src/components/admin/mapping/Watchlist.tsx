"use client";

/**
 * The watchlist (design portal-mapping, decision 7; plan §4.1: "specific cases a department has asked to follow"),
 * under `admin.watchlist`. The CNR is checked in the browser before sending (four letters and twelve digits); a CNR
 * not yet held queues its court details (`dossier_queued`); a held case is scored again at once. Case references
 * link through search, which opens the case when visible and otherwise its court-public summary.
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
  numCell,
  Table,
  TextArea,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { MAPPING_KEY, useMe } from "@/lib/api/hooks";
import type { Watch, WatchList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { given, isCnr, normaliseCnr, officeRequired, weightBody } from "@/lib/mapping";
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

const WATCH_KEY = [...MAPPING_KEY, "watchlist"] as const;

/** After a save: queued details for a CNR not held yet, else the held case was scored again at once. */
function savedLine(row: Watch): string {
  if (row.dossier_queued) return T.mapping.dossierQueued;
  return row.case_ref ? T.mapping.scoredNow : T.saved;
}

export function Watchlist() {
  const me = useMe();
  const canScore = can(me.data, "admin.scoring");
  const choices = useOfficeChoices();
  const queryClient = useQueryClient();
  const officeId = useId();
  const [filter, setFilter] = useState({ office: "", inactive: false });
  const list = useQuery({
    queryKey: [...WATCH_KEY, filter],
    queryFn: () =>
      api<WatchList>("/admin/watchlist", {
        query: { office: filter.office || undefined, include_inactive: filter.inactive || undefined },
      }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: WATCH_KEY });
  const [draft, setDraft] = useState({ cnr: "", office: "", reason: "" });
  const [cnrError, setCnrError] = useState<string | null>(null);
  const [weight, setWeight] = useState<WeightDraft>(weightDraft(null));
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Watch | null>(null);
  const action = useAction();

  async function add(e: FormEvent) {
    e.preventDefault();
    setNotice(null);
    const cnr = normaliseCnr(draft.cnr);
    if (!isCnr(cnr)) {
      setCnrError(T.mapping.badCnr);
      return;
    }
    setCnrError(null);
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<Watch>("/admin/watchlist", {
            method: "POST",
            body: {
              cnr,
              office_code: draft.office.trim() || null,
              reason: draft.reason.trim() || null,
              ...(canScore ? weightBody(weight.changed, weight.value) : {}),
            },
          }),
        () => void refresh(),
      ),
    );
    if (out.ok) {
      setNotice(savedLine(out.value));
      setDraft({ cnr: "", office: "", reason: "" });
      setWeight(weightDraft(null));
      await refresh();
    }
  }

  return (
    <section className="stack" aria-label={T.mapping.watchlist}>
      <h3>{T.mapping.watchlist}</h3>
      <form className={`row ${s.form}`} onSubmit={add} aria-label={T.mapping.addWatch} noValidate>
        <TextField
          label={T.mapping.cnr}
          required
          className="mono"
          maxLength={20}
          autoComplete="off"
          hint={T.mapping.cnrHint}
          error={cnrError}
          value={draft.cnr}
          onChange={(e) => {
            setCnrError(null);
            setDraft({ ...draft, cnr: e.target.value });
          }}
        />
        <OfficePicker
          id={officeId}
          choices={choices}
          optional
          allowRoot={false}
          value={draft.office}
          onChange={(office) => setDraft({ ...draft, office })}
          hint={T.mapping.watchOfficeHint}
          error={officeRequired(action.error) ? (action.error as Error).message : undefined}
        />
        <TextArea
          label={T.mapping.reason}
          maxLength={2000}
          rows={2}
          value={draft.reason}
          onChange={(e) => setDraft({ ...draft, reason: e.target.value })}
        />
        {canScore ? <WeightField mode="create" draft={weight} onChange={setWeight} /> : null}
        <Button type="submit" busy={action.busy}>
          {T.mapping.addWatch}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
      {notice ? <Notice>{notice}</Notice> : null}

      <div className="row">
        <OfficeFilter choices={choices} value={filter.office} onChange={(office) => setFilter({ ...filter, office })} />
        <CheckField
          label={T.mapping.includeInactive}
          checked={filter.inactive}
          onChange={(e) => setFilter({ ...filter, inactive: e.target.checked })}
        />
      </div>
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.mapping.empty}</EmptyState>
        ) : (
          <Table caption={T.mapping.watchlist}>
            <thead>
              <tr>
                <th scope="col">{T.mapping.cnr}</th>
                <th scope="col">{T.mapping.case}</th>
                <th scope="col">{T.mapping.office}</th>
                <th scope="col">{T.mapping.reason}</th>
                <th scope="col" className={numCell}>
                  {T.mapping.effectiveWeight}
                </th>
                <th scope="col">{T.mapping.status}</th>
                <th scope="col">{T.mapping.updated}</th>
                <th scope="col">{T.mapping.actions}</th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.cnr}</td>
                  <td>
                    <SearchLink ref_no={row.case_ref} />
                  </td>
                  <td>
                    <OfficeCell office={row.office} />
                  </td>
                  <td>{row.reason ?? "—"}</td>
                  <td className={numCell}>
                    <WeightCell effective={row.effective_weight} override={row.weight_override} />
                  </td>
                  <td>{row.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>}</td>
                  <td>{formatDateTime(row.updated_at)}</td>
                  <td>
                    <div className="actions">
                      <Button variant="link" aria-label={`${T.edit} ${row.cnr}`} onClick={() => setEditing(row)}>
                        {T.edit}
                      </Button>
                      <RuleStatusActions<Watch>
                        path={`/admin/watchlist/${row.id}`}
                        active={row.is_active}
                        label={row.cnr}
                        confirmText={T.mapping.watchConfirm}
                        onDone={(r) => {
                          setNotice(savedLine(r));
                          void refresh();
                        }}
                        onConflict={() => void refresh()}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )
      ) : null}
      {editing ? (
        <EditWatch
          row={editing}
          canScore={canScore}
          onClose={() => setEditing(null)}
          onSaved={(r) => {
            setEditing(null);
            setNotice(savedLine(r));
            void refresh();
          }}
          onConflict={() => void refresh()}
        />
      ) : null}
    </section>
  );
}

function EditWatch({
  row,
  canScore,
  onClose,
  onSaved,
  onConflict,
}: {
  row: Watch;
  canScore: boolean;
  onClose: () => void;
  onSaved: (row: Watch) => void;
  onConflict: () => void;
}) {
  const [reason, setReason] = useState(row.reason ?? "");
  const [weight, setWeight] = useState<WeightDraft>(weightDraft(row.weight_override));
  const action = useAction();

  async function save() {
    const body: Record<string, unknown> = {
      ...(reason !== (row.reason ?? "") ? { reason } : {}),
      ...(canScore ? weightBody(weight.changed, weight.value) : {}),
    };
    if (Object.keys(body).length === 0) {
      onClose();
      return;
    }
    const out = await action.run(() =>
      conflictAware(() => api<Watch>(`/admin/watchlist/${row.id}`, { method: "PATCH", body }), onConflict),
    );
    if (out.ok) onSaved(out.value);
  }

  return (
    <ConfirmDialog
      open
      title={T.mapping.editWatch(row.cnr)}
      onClose={onClose}
      onConfirm={() => void save()}
      busy={action.busy}
      error={given(action.error)}
      confirmLabel={T.save}
    >
      <TextArea label={T.mapping.reason} maxLength={2000} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      {canScore ? <WeightField mode="edit" draft={weight} onChange={setWeight} current={row.weight_override} /> : null}
    </ConfirmDialog>
  );
}
