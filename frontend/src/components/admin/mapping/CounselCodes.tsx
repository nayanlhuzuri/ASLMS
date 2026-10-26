"use client";

/**
 * Counsel codes (design portal-mapping, decision 5; simplified by portal-ui-polish-2, decisions 39-42; plan §4.1:
 * "each code is mapped to its department in the administration module"). One toolbar line (Search Codes with the
 * list's `q`, Include Deactivated), one add row (Code, Office from the Office Picker, Add Code), the list with a menu
 * per row (Change Office, Deactivate or Reactivate), and "Recommended From Cause Lists" always beside it: the codes
 * seen in cause lists with no mapping, each with its own picker and Map. Nothing is mapped automatically: Map is a
 * person's decision. A code mapped to the root office is generic (recognised, recommends no department); the forms
 * send `is_generic_state` exactly when the root office is chosen. Notes and weights are never sent (decision 39).
 * A code that partly matches mappings in the caller's scope says so ("Partly matches SC, EDU (EDU)"), and with exactly
 * one such mapping its picker starts on that office; Map still sends nothing until pressed (design partial-code-match,
 * decision 16).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  Card,
  DataTable,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  OfficePicker,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { MAPPING_KEY, useOfficeChoices } from "@/lib/api/hooks";
import type { CounselCode, CounselCodeList, OfficeChoice, UnmappedCode } from "@/lib/api/types";
import { formatDate, formatDateTime, formatNumber } from "@/lib/format";
import { given } from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import { conflictAware, isRootChoice, OfficeCell, RuleMenu, RuleToolbar, SearchLink } from "./common";
import s from "./mapping.module.css";

const CODES_KEY = [...MAPPING_KEY, "codes"] as const;
export const UNMAPPED_KEY = [...MAPPING_KEY, "unmapped"] as const;

/** The search words typed, sent as `q` once typing pauses. */
function useSettled(value: string, ms = 300): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}

export function CounselCodes() {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [inactive, setInactive] = useState(false);
  const query = useSettled(q.trim());
  const list = useQuery({
    queryKey: [...CODES_KEY, { q: query, inactive }],
    queryFn: () =>
      api<CounselCodeList>("/admin/counsel-codes", {
        query: { q: query || undefined, include_inactive: inactive || undefined },
      }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: CODES_KEY });
  const [notice, setNotice] = useState<string | null>(null);
  // a generic code (on the root office) is managed only by a login whose scope holds the root office
  const choices = useOfficeChoices("counsel_codes");
  const editableGeneric = (choices.data?.items ?? []).some((o) => isRootChoice(o));

  function saved(row: CounselCode) {
    setNotice(T.mapping.appliesWithin(row.applies_within_minutes ?? 15));
    // the mapped code leaves the recommended panel without scanning the cause lists again
    queryClient.setQueryData<UnmappedCode[]>(UNMAPPED_KEY, (old) => old?.filter((u) => u.code !== row.code));
    void refresh();
  }

  return (
    <section className="stack" aria-label={T.mapping.codes}>
      <h3>{T.mapping.codes}</h3>
      <div className={s.codesLayout}>
        <div className={s.codesMain}>
          <RuleToolbar
            searchLabel={T.mapping.searchCodesLabel}
            placeholder={T.mapping.searchCodesPlaceholder}
            q={q}
            onQ={setQ}
            inactive={inactive}
            onInactive={setInactive}
          />
          <AddCode onSaved={saved} onConflict={() => void refresh()} />
          {notice ? <Notice>{notice}</Notice> : null}
          {list.isPending ? <Loading /> : null}
          <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
          {list.data ? (
            list.data.items.length === 0 ? (
              <EmptyState>{T.mapping.empty}</EmptyState>
            ) : (
              <div className={s.scrollBox} tabIndex={0} role="region" aria-label={T.mapping.codes}>
                <DataTable
                  caption={T.mapping.codes}
                  rows={list.data.items}
                  rowKey={(row) => row.id}
                  columns={[
                    { key: "code", header: T.mapping.code, primary: true, cell: (row) => <span className="mono">{row.code}</span> },
                    { key: "office", header: T.mapping.office, cell: (row) => <OfficeCell office={row.office} /> },
                    { key: "generic", header: T.mapping.generic, cell: (row) => (row.is_generic_state ? T.yes : "—") },
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
                      cell: (row) =>
                        row.is_generic_state && !editableGeneric ? null : (
                        <RuleMenu<CounselCode>
                          path={`/admin/counsel-codes/${row.id}`}
                          active={row.is_active}
                          label={row.code}
                          confirmText={T.mapping.ruleConfirm}
                          onDone={(r) => saved(r)}
                          onConflict={() => void refresh()}
                          office={{
                            purpose: "counsel_codes",
                            current: row.office.code,
                            // a generic code stays generic (the root office); any other code moves among departments
                            kinds: row.is_generic_state ? ["state"] : undefined,
                            body: (_choice, code) => ({ office_code: code }),
                          }}
                        />
                      ),
                    },
                  ]}
                />
              </div>
            )
          ) : null}
        </div>
        <RecommendedCodes onMapped={saved} onConflict={() => void refresh()} />
      </div>
    </section>
  );
}

/** The add row (decision 41): Code, Office (picker), Add Code; secondary, so the page keeps no primary of its own. */
function AddCode({ onSaved, onConflict }: { onSaved: (row: CounselCode) => void; onConflict: () => void }) {
  const [code, setCode] = useState("");
  const [office, setOffice] = useState<string | null>(null);
  const [chosen, setChosen] = useState<OfficeChoice | undefined>(undefined);
  const action = useAction();
  const generic = isRootChoice(chosen);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!office) return;
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<CounselCode>("/admin/counsel-codes", {
            method: "POST",
            body: { code: code.trim(), office_code: office, is_generic_state: generic },
          }),
        onConflict,
      ),
    );
    if (out.ok) {
      setCode("");
      setOffice(null);
      setChosen(undefined);
      onSaved(out.value);
    }
  }

  return (
    <>
      <form className={s.addRow} onSubmit={add} aria-label={T.mapping.addCode}>
        <div className={s.narrow}>
          <TextField label={T.mapping.code} required maxLength={60} title={T.mapping.codeHint} value={code} onChange={(e) => setCode(e.target.value)} />
        </div>
        <OfficePicker
          label={T.mapping.office}
          purpose="counsel_codes"
          required
          value={office}
          onChange={setOffice}
          onChoose={setChosen}
          hint={generic ? T.mapping.genericLine : undefined}
        />
        <Button type="submit" variant="secondary" busy={action.busy} disabled={!office || !code.trim()}>
          {T.mapping.addCode}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
    </>
  );
}

/**
 * "Recommended From Cause Lists" (decision 42): the codes seen in cause lists with no mapping
 * (`GET /admin/counsel-codes/unmapped?limit=100`), always shown, each with its entries, when it was last seen, an
 * example case, and its own picker with Map, which posts the mapping directly. The code then leaves the panel.
 */
export function RecommendedCodes({ onMapped, onConflict }: { onMapped: (row: CounselCode) => void; onConflict: () => void }) {
  const list = useQuery({
    queryKey: UNMAPPED_KEY,
    queryFn: () => api<UnmappedCode[]>("/admin/counsel-codes/unmapped", { query: { limit: 100 } }),
    staleTime: 10 * 60_000,
    retry: false,
  });
  return (
    <aside className={s.recommended} aria-label={T.mapping.recommendedTitle}>
      <Card title={T.mapping.recommendedTitle} actions={list.data ? <span className="muted">{T.mapping.toReview(list.data.length)}</span> : null}>
        <div className="stack">
          <Notice>{T.mapping.recommendedNotice}</Notice>
          {list.isPending ? <Loading /> : null}
          <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
          {list.data ? (
            list.data.length === 0 ? (
              <EmptyState>{T.mapping.noUnmapped}</EmptyState>
            ) : (
              <div className={s.scrollBox} tabIndex={0} role="region" aria-label={T.mapping.recommendedTitle}>
                <ul className={s.recList}>
                  {list.data.map((u) => (
                    <RecommendedCode key={u.code} item={u} onMapped={onMapped} onConflict={onConflict} />
                  ))}
                </ul>
              </div>
            )
          ) : null}
        </div>
      </Card>
    </aside>
  );
}

function RecommendedCode({ item, onMapped, onConflict }: { item: UnmappedCode; onMapped: (row: CounselCode) => void; onConflict: () => void }) {
  const partial = item.partial_matches ?? [];
  const [office, setOffice] = useState<string | null>(partial.length === 1 ? partial[0]!.office_code : null);
  const [chosen, setChosen] = useState<OfficeChoice | undefined>(undefined);
  const action = useAction();

  async function map(e: FormEvent) {
    e.preventDefault();
    if (!office) return;
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<CounselCode>("/admin/counsel-codes", {
            method: "POST",
            body: { code: item.code, office_code: office, is_generic_state: isRootChoice(chosen) },
          }),
        onConflict,
      ),
    );
    if (out.ok) onMapped(out.value);
  }

  return (
    <li>
      <div className={s.recTop}>
        <span className="mono">{item.code}</span>
        <span className="muted">{T.mapping.entriesLine(formatNumber(item.entries), formatDate(item.last_listed))}</span>
      </div>
      {partial.length > 0 ? <span className="muted">{T.mapping.partlyMatches(partial)}</span> : null}
      {item.example_case_ref ? <SearchLink ref_no={item.example_case_ref} /> : null}
      <form className={s.recMap} onSubmit={map} aria-label={T.mapping.mapCode(item.code)}>
        <OfficePicker label={T.mapping.officeFor(item.code)} hideLabel purpose="counsel_codes" value={office} onChange={setOffice} onChoose={setChosen} />
        <Button type="submit" variant="secondary" busy={action.busy} disabled={!office} aria-label={T.mapping.mapCode(item.code)}>
          {T.mapping.map}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
    </li>
  );
}
