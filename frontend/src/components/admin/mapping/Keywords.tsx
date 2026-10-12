"use client";

/**
 * Keywords and name patterns (design portal-mapping, decision 6; plan §4.1: "department names and designations
 * appearing in the party names"; §5.11), both under `admin.keywords`, two tables on one page. The API's `PATCH` takes
 * the weight only, so Edit shows only with `admin.scoring`; a wording change is a deactivation and a new rule. Adding
 * a rule that exists deactivated reactivates it (the API's behaviour); the screen says so when it knew the row.
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
  SelectField,
  Table,
  TextField,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { MAPPING_KEY, useMe } from "@/lib/api/hooks";
import type { Keyword, KeywordList, NamePattern, NamePatternList } from "@/lib/api/types";
import { can } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { given, weightBody } from "@/lib/mapping";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

import {
  conflictAware,
  OfficeCell,
  OfficeFilter,
  OfficePicker,
  RuleStatusActions,
  useOfficeChoices,
  WeightCell,
  weightDraft,
  WeightField,
  type OfficeChoices,
  type WeightDraft,
} from "./common";
import s from "./mapping.module.css";

const KEYWORDS_KEY = [...MAPPING_KEY, "keywords"] as const;
const PATTERNS_KEY = [...MAPPING_KEY, "name-patterns"] as const;
const KINDS = ["exact", "prefix", "regex"] as const;

interface Filter {
  office: string;
  inactive: boolean;
}

function ListFilter({ choices, filter, onChange }: { choices: OfficeChoices; filter: Filter; onChange: (f: Filter) => void }) {
  return (
    <div className="row">
      <OfficeFilter choices={choices} value={filter.office} onChange={(office) => onChange({ ...filter, office })} />
      <CheckField
        label={T.mapping.includeInactive}
        checked={filter.inactive}
        onChange={(e) => onChange({ ...filter, inactive: e.target.checked })}
      />
    </div>
  );
}

export function KeywordsAndPatterns() {
  return (
    <div className="stack">
      <Keywords />
      <NamePatterns />
    </div>
  );
}

function Keywords() {
  const me = useMe();
  const canScore = can(me.data, "admin.scoring");
  const choices = useOfficeChoices();
  const queryClient = useQueryClient();
  const officeId = useId();
  const [filter, setFilter] = useState<Filter>({ office: "", inactive: false });
  const list = useQuery({
    queryKey: [...KEYWORDS_KEY, filter],
    queryFn: () =>
      api<KeywordList>("/admin/keywords", {
        query: { office: filter.office || undefined, include_inactive: filter.inactive || undefined },
      }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: KEYWORDS_KEY });
  const [draft, setDraft] = useState({ keyword: "", office: "" });
  const [weight, setWeight] = useState<WeightDraft>(weightDraft(null));
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<Keyword | null>(null);
  const action = useAction();

  async function add(e: FormEvent) {
    e.preventDefault();
    setNotice(null);
    const known = new Set((list.data?.items ?? []).map((r) => r.id));
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<Keyword>("/admin/keywords", {
            method: "POST",
            body: {
              keyword: draft.keyword.trim(),
              office_code: draft.office.trim(),
              ...(canScore ? weightBody(weight.changed, weight.value) : {}),
            },
          }),
        () => void refresh(),
      ),
    );
    if (out.ok) {
      const line = T.mapping.appliesWithin(out.value.applies_within_minutes ?? 15);
      setNotice(known.has(out.value.id) ? `${T.mapping.reactivated} ${line}` : line);
      setDraft({ keyword: "", office: "" });
      setWeight(weightDraft(null));
      await refresh();
    }
  }

  return (
    <section className="stack" aria-label={T.mapping.keywords}>
      <h3>{T.mapping.keywords}</h3>
      <form className={`row ${s.form}`} onSubmit={add} aria-label={T.mapping.addKeyword}>
        <TextField
          label={T.mapping.keyword}
          required
          maxLength={200}
          hint={T.mapping.keywordHint}
          value={draft.keyword}
          onChange={(e) => setDraft({ ...draft, keyword: e.target.value })}
        />
        <OfficePicker id={officeId} choices={choices} required value={draft.office} onChange={(office) => setDraft({ ...draft, office })} />
        {canScore ? <WeightField mode="create" draft={weight} onChange={setWeight} /> : null}
        <Button type="submit" busy={action.busy}>
          {T.mapping.addKeyword}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
      {notice ? <Notice>{notice}</Notice> : null}
      <ListFilter choices={choices} filter={filter} onChange={setFilter} />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.mapping.empty}</EmptyState>
        ) : (
          <Table caption={T.mapping.keywords}>
            <thead>
              <tr>
                <th scope="col">{T.mapping.keyword}</th>
                <th scope="col">{T.mapping.office}</th>
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
                  <td>{row.keyword}</td>
                  <td>
                    <OfficeCell office={row.office} />
                  </td>
                  <td className={numCell}>
                    <WeightCell effective={row.effective_weight} override={row.weight_override} />
                  </td>
                  <td>{row.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>}</td>
                  <td>{formatDateTime(row.updated_at)}</td>
                  <td>
                    <div className="actions">
                      {canScore ? (
                        <Button variant="link" aria-label={`${T.edit} ${row.keyword}`} onClick={() => setEditing(row)}>
                          {T.edit}
                        </Button>
                      ) : null}
                      <RuleStatusActions<Keyword>
                        path={`/admin/keywords/${row.id}`}
                        active={row.is_active}
                        label={row.keyword}
                        confirmText={T.mapping.ruleConfirm}
                        onDone={(r) => {
                          setNotice(T.mapping.appliesWithin(r.applies_within_minutes ?? 15));
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
      {editing && canScore ? (
        <EditWeight<Keyword>
          path={`/admin/keywords/${editing.id}`}
          what={editing.keyword}
          current={editing.weight_override}
          onClose={() => setEditing(null)}
          onSaved={(r) => {
            setEditing(null);
            setNotice(T.mapping.appliesWithin(r.applies_within_minutes ?? 15));
            void refresh();
          }}
          onConflict={() => void refresh()}
        />
      ) : null}
    </section>
  );
}

function NamePatterns() {
  const me = useMe();
  const canScore = can(me.data, "admin.scoring");
  const choices = useOfficeChoices();
  const queryClient = useQueryClient();
  const officeId = useId();
  const [filter, setFilter] = useState<Filter>({ office: "", inactive: false });
  const list = useQuery({
    queryKey: [...PATTERNS_KEY, filter],
    queryFn: () =>
      api<NamePatternList>("/admin/name-patterns", {
        query: { office: filter.office || undefined, include_inactive: filter.inactive || undefined },
      }),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: PATTERNS_KEY });
  const [draft, setDraft] = useState({ pattern: "", kind: "exact", office: "" });
  const [weight, setWeight] = useState<WeightDraft>(weightDraft(null));
  const [notice, setNotice] = useState<string | null>(null);
  const [editing, setEditing] = useState<NamePattern | null>(null);
  const action = useAction();

  async function add(e: FormEvent) {
    e.preventDefault();
    setNotice(null);
    const known = new Set((list.data?.items ?? []).map((r) => r.id));
    const out = await action.run(() =>
      conflictAware(
        () =>
          api<NamePattern>("/admin/name-patterns", {
            method: "POST",
            body: {
              pattern: draft.pattern.trim(),
              kind: draft.kind,
              office_code: draft.office.trim(),
              ...(canScore ? weightBody(weight.changed, weight.value) : {}),
            },
          }),
        () => void refresh(),
      ),
    );
    if (out.ok) {
      const line = T.mapping.appliesWithin(out.value.applies_within_minutes ?? 15);
      setNotice(known.has(out.value.id) ? `${T.mapping.reactivated} ${line}` : line);
      setDraft({ pattern: "", kind: draft.kind, office: "" });
      setWeight(weightDraft(null));
      await refresh();
    }
  }

  return (
    <section className="stack" aria-label={T.mapping.patterns}>
      <h3>{T.mapping.patterns}</h3>
      <form className={`row ${s.form}`} onSubmit={add} aria-label={T.mapping.addPattern}>
        <TextField
          label={T.mapping.pattern}
          required
          maxLength={300}
          value={draft.pattern}
          onChange={(e) => setDraft({ ...draft, pattern: e.target.value })}
        />
        <SelectField
          label={T.mapping.kind}
          options={KINDS.map((k) => ({ value: k, label: T.mapping.kinds[k]! }))}
          value={draft.kind}
          onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
        />
        <OfficePicker id={officeId} choices={choices} required value={draft.office} onChange={(office) => setDraft({ ...draft, office })} />
        {canScore ? <WeightField mode="create" draft={weight} onChange={setWeight} /> : null}
        <Button type="submit" busy={action.busy}>
          {T.mapping.addPattern}
        </Button>
      </form>
      <ErrorBanner error={given(action.error)} />
      {notice ? <Notice>{notice}</Notice> : null}
      <ListFilter choices={choices} filter={filter} onChange={setFilter} />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={given(list.error)} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{T.mapping.empty}</EmptyState>
        ) : (
          <Table caption={T.mapping.patterns}>
            <thead>
              <tr>
                <th scope="col">{T.mapping.pattern}</th>
                <th scope="col">{T.mapping.kind}</th>
                <th scope="col">{T.mapping.office}</th>
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
                  <td className="mono">{row.pattern}</td>
                  <td>{T.mapping.kindShort[row.kind] ?? row.kind}</td>
                  <td>
                    <OfficeCell office={row.office} />
                  </td>
                  <td className={numCell}>
                    <WeightCell effective={row.effective_weight} override={row.weight_override} />
                  </td>
                  <td>{row.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>}</td>
                  <td>{formatDateTime(row.updated_at)}</td>
                  <td>
                    <div className="actions">
                      {canScore ? (
                        <Button variant="link" aria-label={`${T.edit} ${row.pattern}`} onClick={() => setEditing(row)}>
                          {T.edit}
                        </Button>
                      ) : null}
                      <RuleStatusActions<NamePattern>
                        path={`/admin/name-patterns/${row.id}`}
                        active={row.is_active}
                        label={row.pattern}
                        confirmText={T.mapping.ruleConfirm}
                        onDone={(r) => {
                          setNotice(T.mapping.appliesWithin(r.applies_within_minutes ?? 15));
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
      {editing && canScore ? (
        <EditWeight<NamePattern>
          path={`/admin/name-patterns/${editing.id}`}
          what={editing.pattern}
          current={editing.weight_override}
          onClose={() => setEditing(null)}
          onSaved={(r) => {
            setEditing(null);
            setNotice(T.mapping.appliesWithin(r.applies_within_minutes ?? 15));
            void refresh();
          }}
          onConflict={() => void refresh()}
        />
      ) : null}
    </section>
  );
}

/** The weight-only edit of a keyword or a name pattern (`PATCH {weight}`), for `admin.scoring` only. */
function EditWeight<R>({
  path,
  what,
  current,
  onClose,
  onSaved,
  onConflict,
}: {
  path: string;
  what: string;
  current: number | null;
  onClose: () => void;
  onSaved: (row: R) => void;
  onConflict: () => void;
}) {
  const [weight, setWeight] = useState<WeightDraft>(weightDraft(current));
  const action = useAction();

  async function save() {
    const body = weightBody(weight.changed, weight.value);
    if (!("weight" in body)) {
      onClose();
      return;
    }
    const out = await action.run(() => conflictAware(() => api<R>(path, { method: "PATCH", body }), onConflict));
    if (out.ok) onSaved(out.value);
  }

  return (
    <ConfirmDialog
      open
      title={T.mapping.editWeight(what)}
      onClose={onClose}
      onConfirm={() => void save()}
      busy={action.busy}
      error={given(action.error)}
      confirmLabel={T.save}
    >
      <WeightField mode="edit" draft={weight} onChange={setWeight} current={current} />
    </ConfirmDialog>
  );
}
