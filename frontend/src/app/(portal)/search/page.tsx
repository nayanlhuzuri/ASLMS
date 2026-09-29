"use client";

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { CardList, TrackingCard } from "@/components/case/CaseBits";
import { useOffices } from "@/components/shell/MeContext";
import { Button } from "@/components/ui/Button";
import { Check, Field, FormRow, Select, TextInput } from "@/components/ui/Field";
import { Card, Notice, PageHeader } from "@/components/ui/Layout";
import { Pagination } from "@/components/ui/Pagination";
import { Async, Empty, Loading } from "@/components/ui/States";
import { fmtNumber } from "@/lib/format";
import { useConfig } from "@/lib/config";
import { useApi } from "@/lib/hooks";
import type { CaseType, LiveSearch, SearchOut } from "@/lib/types";
import { useUrlState } from "@/lib/urlState";

const FILTERS = ["q", "status", "year", "case_type", "department_id", "ownership", "advocate", "party", "mine"] as const;
type FilterKey = (typeof FILTERS)[number];
type Draft = Record<FilterKey, string>;

function LiveNote({ live, total }: { live: LiveSearch; total: number }) {
  if (!live.napix) return null;
  if (live.napix === "not configured") {
    return <Notice tone="warning">Not found in the portal. The court API is not configured, so the court database was not searched.</Notice>;
  }
  if (live.napix === "error") {
    return <Notice tone="warning">Not found in the portal. The court database could not be searched just now{live.error ? ` (${live.error})` : ""}.</Notice>;
  }
  const stored = live.stored ?? 0;
  return (
    <Notice>
      Not found in the portal; the court database was searched.{" "}
      {stored > 0
        ? `${fmtNumber(stored)} ${stored === 1 ? "case was" : "cases were"} fetched from the court and added to the portal.`
        : total === 0
          ? "Nothing matching was found there either."
          : ""}
    </Notice>
  );
}

function SearchInner() {
  const url = useUrlState();
  const { departments } = useOffices();
  const caseTypes = useApi<CaseType[]>("/masters/case-types");
  const { config, loaded } = useConfig();
  const current: Draft = Object.fromEntries(FILTERS.map((k) => [k, url.get(k)])) as Draft;
  const [draft, setDraft] = useState<Draft>(current);
  const page = Number(url.get("page", "1")) || 1;
  const paramsKey = url.params.toString();

  useEffect(() => {
    setDraft(Object.fromEntries(FILTERS.map((k) => [k, url.get(k)])) as Draft);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramsKey]);

  const hasQuery = FILTERS.some((k) => current[k]);
  const results = useApi<SearchOut>(hasQuery ? "/search" : null, {
    q: current.q || undefined,
    status: current.status || undefined,
    year: current.year || undefined,
    case_type: current.case_type || undefined,
    department_id: current.department_id || undefined,
    ownership: current.ownership || undefined,
    advocate: current.advocate || undefined,
    party: current.party || undefined,
    mine: current.mine === "true" ? true : undefined,
    page,
    size: 25,
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    url.set({ ...Object.fromEntries(FILTERS.map((k) => [k, draft[k].trim()])), page: null }, { push: true });
  };
  const clear = () => {
    setDraft(Object.fromEntries(FILTERS.map((k) => [k, ""])) as Draft);
    url.set({ ...Object.fromEntries(FILTERS.map((k) => [k, null])), page: null }, { push: true });
  };
  const upd = (k: FilterKey) => (v: string) => setDraft((d) => ({ ...d, [k]: v }));
  const thisYear = new Date().getFullYear();

  return (
    <>
      <PageHeader title="Search" sub="The portal database first; when nothing is found, the court database is searched and the case is added." />
      <Card>
        <form role="search" onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <FormRow>
            <Field label="CINO, case number, portal reference, party or advocate" className="grow">
              <TextInput
                type="search"
                value={draft.q}
                onChange={(e) => upd("q")(e.target.value)}
                placeholder="e.g. WP(C)/1234/2026, GAHC010012342026 or ASLMS/GOA/CASE/2026/000123"
              />
            </Field>
          </FormRow>
          <FormRow>
            <Field label="Status">
              <Select value={draft.status} onChange={(e) => upd("status")(e.target.value)}>
                <option value="">Any</option>
                <option value="pending">Pending</option>
                <option value="disposed">Disposed</option>
              </Select>
            </Field>
            <Field label="Case type">
              <Select value={draft.case_type} onChange={(e) => upd("case_type")(e.target.value)}>
                <option value="">Any</option>
                {(caseTypes.data ?? []).map((t) => (
                  <option key={t.id} value={t.type_name}>
                    {t.type_name}
                    {t.full_name ? ` - ${t.full_name}` : ""}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Year">
              <TextInput
                type="number"
                inputMode="numeric"
                min={1948}
                max={thisYear}
                value={draft.year}
                onChange={(e) => upd("year")(e.target.value)}
                placeholder={String(thisYear)}
              />
            </Field>
            <Field label="Department">
              <Select value={draft.department_id} onChange={(e) => upd("department_id")(e.target.value)}>
                <option value="">Any</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Claimed">
              <Select value={draft.ownership} onChange={(e) => upd("ownership")(e.target.value)}>
                <option value="">Claimed or not</option>
                <option value="claimed">Claimed</option>
                <option value="unclaimed">Unclaimed</option>
              </Select>
            </Field>
          </FormRow>
          <FormRow>
            <Field label="Advocate">
              <TextInput value={draft.advocate} onChange={(e) => upd("advocate")(e.target.value)} />
            </Field>
            <Field label="Party">
              <TextInput value={draft.party} onChange={(e) => upd("party")(e.target.value)} />
            </Field>
            <div style={{ display: "flex", alignItems: "flex-end" }}>
              <Check label="Only my cases" checked={draft.mine === "true"} onChange={(e) => upd("mine")(e.target.checked ? "true" : "")} />
            </div>
          </FormRow>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Button type="submit" variant="primary" icon="search">
              Search
            </Button>
            <Button onClick={clear}>Clear</Button>
          </div>
        </form>
      </Card>
      {loaded && !config.napix_enabled ? (
        <Notice tone="warning">Court API not configured: only the portal database is searched. Cases not yet in the portal cannot be fetched from the court.</Notice>
      ) : null}
      {!hasQuery ? (
        <Empty title="Search for a case" center>
          Enter a CINO, a case number such as WP(C)/1234/2026, or a party or advocate name, or choose filters.
        </Empty>
      ) : (
        <Async state={results} loadingLabel="Searching">
          {(r) => (
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }} aria-live="polite">
              <LiveNote live={r.live as LiveSearch} total={r.total} />
              {r.items.length === 0 ? (
                <Empty title="No case found" center>
                  Check the number or name, or widen the filters.
                </Empty>
              ) : (
                <>
                  <div className="muted" style={{ fontSize: 14 }}>
                    {fmtNumber(r.total)} {r.total === 1 ? "case" : "cases"} found
                  </div>
                  <CardList>
                    {r.items.map((c) => (
                      <TrackingCard key={c.id} c={c} />
                    ))}
                  </CardList>
                  <Pagination page={r.page} size={r.size} total={r.total} onPage={(p) => url.set({ page: p > 1 ? p : null })} noun="cases" />
                </>
              )}
            </div>
          )}
        </Async>
      )}
    </>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<Loading />}>
      <SearchInner />
    </Suspense>
  );
}
