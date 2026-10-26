"use client";

/**
 * The watchlist (design portal-mapping, decision 7; simplified by portal-ui-polish-2, decisions 39-41; plan §4.1:
 * "specific cases a department has asked to follow"), under `admin.watchlist`. One toolbar line (Search Watchlist,
 * Include Deactivated), one add row (CNR, checked in the browser before sending: four letters and twelve digits;
 * Office from the Office Picker, left empty for the caller's own department; Add), and a menu per row (Deactivate or
 * Reactivate). A CNR not yet held queues its court details (`dossier_queued`); a held case is scored again at once.
 * Case references link through search. No weight or reason is sent from the forms.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Badge, Button, DataTable, EmptyState, ErrorBanner, Loading, Notice, OfficePicker, TextField } from "@/components/ui";
import { api } from "@/lib/api/client";
import { MAPPING_KEY } from "@/lib/api/hooks";
import type { Watch, WatchList } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { given, isCnr, normaliseCnr, officeRequired } from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import { conflictAware, matches, OfficeCell, RuleMenu, RuleToolbar, SearchLink } from "./common";
import s from "./mapping.module.css";

const WATCH_KEY = [...MAPPING_KEY, "watchlist"] as const;
/** Every kind but the State: a watch belongs to a department or an office below it. */
const WATCH_KINDS = ["department", "central", "advocate_general", "directorate", "unit"];

/** After a save: queued details for a CNR not held yet, else the held case was scored again at once. */
function savedLine(row: Watch): string {
  if (row.dossier_queued) return T.mapping.dossierQueued;
  return row.case_ref ? T.mapping.scoredNow : T.saved;
}

export function Watchlist() {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [inactive, setInactive] = useState(false);
  const list = useQuery({
    queryKey: [...WATCH_KEY, { inactive }],
    queryFn: () => api<WatchList>("/admin/watchlist", { query: { include_inactive: inactive || undefined } }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: WATCH_KEY });
  const [notice, setNotice] = useState<string | null>(null);
  const rows = (list.data?.items ?? []).filter((r) => matches(q, r.cnr, r.case_ref, r.office.name, r.office.code, r.reason));

  return (
    <section className="stack" aria-label={T.mapping.watchlist}>
      <h3>{T.mapping.watchlist}</h3>
      <RuleToolbar
        searchLabel={T.mapping.searchWatchLabel}
        placeholder={T.mapping.searchWatchPlaceholder}
        q={q}
        onQ={setQ}
        inactive={inactive}
        onInactive={setInactive}
      />
      <AddWatch
        onSaved={(row) => {
          setNotice(savedLine(row));
          void refresh();
        }}
        onConflict={() => void refresh()}
      />
      {notice ? <Notice>{notice}</Notice> : null}
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
      {list.data ? (
        rows.length === 0 ? (
          <EmptyState>{T.mapping.empty}</EmptyState>
        ) : (
          <div className={s.scrollBox} tabIndex={0} role="region" aria-label={T.mapping.watchlist}>
            <DataTable
              caption={T.mapping.watchlist}
              rows={rows}
              rowKey={(row) => row.id}
              columns={[
                { key: "cnr", header: T.mapping.cnr, primary: true, cell: (row) => <span className="mono">{row.cnr}</span> },
                { key: "case", header: T.mapping.case, cell: (row) => <SearchLink ref_no={row.case_ref} /> },
                { key: "office", header: T.mapping.office, cell: (row) => <OfficeCell office={row.office} /> },
                { key: "reason", header: T.mapping.reason, cell: (row) => row.reason ?? "—" },
                {
                  key: "status",
                  header: T.mapping.status,
                  width: "var(--lead-w)",
                  cell: (row) => (row.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>),
                },
                { key: "updated", header: T.mapping.updated, cell: (row) => formatDateTime(row.updated_at) },
                {
                  key: "actions",
                  header: <span className="visually-hidden">{T.mapping.actions}</span>,
                  label: T.mapping.actions,
                  width: "var(--s7)",
                  align: "right",
                  cell: (row) => (
                    <RuleMenu<Watch>
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
                  ),
                },
              ]}
            />
          </div>
        )
      ) : null}
    </section>
  );
}

/** The add row (decision 41): CNR, Office (picker, optional) and Add. */
function AddWatch({ onSaved, onConflict }: { onSaved: (row: Watch) => void; onConflict: () => void }) {
  const [cnr, setCnr] = useState("");
  const [office, setOffice] = useState<string | null>(null);
  const [cnrError, setCnrError] = useState<string | null>(null);
  const action = useAction();

  async function add(e: FormEvent) {
    e.preventDefault();
    const value = normaliseCnr(cnr);
    if (!isCnr(value)) {
      setCnrError(T.mapping.badCnr);
      return;
    }
    setCnrError(null);
    const out = await action.run(() =>
      conflictAware(() => api<Watch>("/admin/watchlist", { method: "POST", body: { cnr: value, office_code: office } }), onConflict),
    );
    if (out.ok) {
      setCnr("");
      setOffice(null);
      onSaved(out.value);
    }
  }

  return (
    <>
      <form className={s.addRow} onSubmit={add} aria-label={T.mapping.watchlist} noValidate>
        <div className={s.narrow}>
          <TextField
            label={T.mapping.cnr}
            required
            className="mono"
            maxLength={20}
            autoComplete="off"
            title={T.mapping.cnrHint}
            error={cnrError}
            value={cnr}
            onChange={(e) => {
              setCnrError(null);
              setCnr(e.target.value);
            }}
          />
        </div>
        <OfficePicker
          label={T.mapping.office}
          purpose="watchlist"
          kinds={WATCH_KINDS}
          placeholder={T.mapping.ownDepartmentPlaceholder}
          hint={T.mapping.watchOfficeHint}
          value={office}
          onChange={setOffice}
          error={officeRequired(action.error) ? (action.error as Error).message : undefined}
        />
        <Button type="submit" variant="secondary" busy={action.busy}>
          {T.mapping.add}
        </Button>
      </form>
      {officeRequired(action.error) ? null : <ErrorBanner error={given(action.error)} />}
    </>
  );
}
