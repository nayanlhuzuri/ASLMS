"use client";

/**
 * "Search the court" (design portal-cases, decision 9; plan Figure 7, local first): with `cases.search_court`, by CNR,
 * by case type + number + year, or by party name + year + pending / disposed / both. The answer lists the cases found
 * (now stored, so the next local search finds them), the court calls used, the cases created and the party rows the
 * court returned that are not stored; a row without court details offers "Fetch details". The button is disabled
 * while a search runs and a court search is never repeated automatically.
 */
import { useState } from "react";

import { Button, CaseLink, EmptyState, ErrorBanner, Notice, SelectField, TextField } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import { useCaseTypes } from "@/lib/api/hooks";
import type { CaseSearchItem, CourtSearchOut } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { apiCasePath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

import { CaseResults } from "./CaseResults";

type Kind = "cnr" | "case_number" | "party";

function FetchDetails({ item, onFetched }: { item: CaseSearchItem; onFetched: (next: CaseSearchItem) => void }) {
  const action = useAction();
  async function fetchIt() {
    const out = await action.run(() =>
      api<CaseSearchItem>(apiCasePath(item.case.ref_no, "fetch-court"), { method: "POST" }),
    );
    if (out.ok) onFetched(out.value);
  }
  return (
    <span>
      <Button variant="secondary" busy={action.busy} onClick={fetchIt}>
        {T.search.fetchDetails}
      </Button>
      {action.error ? <ErrorBanner error={action.error} /> : null}
      {action.error instanceof ApiError && action.error.code === "already_fetched" ? <CaseLink value={item.case} /> : null}
    </span>
  );
}

export function CourtSearch({ initialQuery, prominent }: { initialQuery?: string; prominent?: boolean }) {
  const q = (initialQuery ?? "").trim();
  const looksCnr = /^[A-Za-z]{4}\d{12}$/.test(q);
  const [kind, setKind] = useState<Kind>(looksCnr || !q ? "cnr" : "party");
  const [cnr, setCnr] = useState(looksCnr ? q.toUpperCase() : "");
  const [caseType, setCaseType] = useState("");
  const [regNo, setRegNo] = useState("");
  const [regYear, setRegYear] = useState("");
  const [party, setParty] = useState(!looksCnr ? q : "");
  const [pendDisp, setPendDisp] = useState("P");
  const [result, setResult] = useState<CourtSearchOut | null>(null);
  const types = useCaseTypes(kind === "case_number");
  const action = useAction();

  function body(): Record<string, unknown> {
    if (kind === "cnr") return { kind, cnr: cnr.trim().toUpperCase() };
    if (kind === "case_number") return { kind, case_type: caseType, reg_no: Number(regNo), reg_year: Number(regYear) };
    return { kind, name: party.trim(), reg_year: Number(regYear), pend_disp: pendDisp };
  }

  async function search() {
    if (action.busy) return;
    setResult(null);
    const out = await action.run(() => api<CourtSearchOut>("/cases/search-court", { method: "POST", body: body() }));
    if (out.ok) setResult(out.value);
  }

  function replaceItem(next: CaseSearchItem) {
    setResult((r) => (r ? { ...r, items: r.items.map((i) => (i.case.id === next.case.id ? next : i)) } : r));
  }

  const err = action.error;
  return (
    <section className="card stack" aria-label={T.search.court}>
      <h2>{T.search.court}</h2>
      {prominent ? <p>{T.search.courtHint}</p> : <p className="muted">{T.search.courtHint}</p>}
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <SelectField
          label={T.search.courtBy}
          options={[
            { value: "cnr", label: T.search.byCnr },
            { value: "case_number", label: T.search.byNumber },
            { value: "party", label: T.search.byParty },
          ]}
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
        />
        {kind === "cnr" ? (
          <TextField
            label={T.search.cnr}
            required
            minLength={16}
            maxLength={16}
            pattern="[A-Za-z]{4}[0-9]{12}"
            className="mono"
            value={cnr}
            onChange={(e) => setCnr(e.target.value)}
          />
        ) : null}
        {kind === "case_number" ? (
          <div className="row">
            <SelectField
              label={T.search.caseType}
              required
              options={(types.data ?? []).map((t) => ({
                value: t.short_name ?? String(t.case_type_code),
                label: t.short_name ? `${t.short_name}${t.full_name ? ` — ${t.full_name}` : ""}` : t.type_name,
              }))}
              placeholder={T.search.anyType}
              value={caseType}
              onChange={(e) => setCaseType(e.target.value)}
            />
            <TextField label={T.search.regNo} required type="number" min={1} value={regNo} onChange={(e) => setRegNo(e.target.value)} />
            <TextField label={T.search.regYear} required type="number" min={1950} max={2100} value={regYear} onChange={(e) => setRegYear(e.target.value)} />
          </div>
        ) : null}
        {kind === "party" ? (
          <div className="row">
            <TextField label={T.search.party} required minLength={3} maxLength={200} value={party} onChange={(e) => setParty(e.target.value)} />
            <TextField label={T.search.regYear} required type="number" min={1950} max={2100} value={regYear} onChange={(e) => setRegYear(e.target.value)} />
            <SelectField
              label={T.search.pendDisp}
              options={Object.entries(T.search.pendDispOptions).map(([value, label]) => ({ value, label }))}
              value={pendDisp}
              onChange={(e) => setPendDisp(e.target.value)}
            />
          </div>
        ) : null}
        <div>
          <Button type="submit" busy={action.busy}>
            {T.search.courtGo}
          </Button>
        </div>
      </form>
      <ErrorBanner error={err} />
      {result ? (
        <div className="stack">
          <Notice>{T.search.courtFound(result.items.length, result.calls, result.created)}</Notice>
          {result.items.length === 0 ? (
            <EmptyState>{T.search.none}</EmptyState>
          ) : (
            <CaseResults
              items={result.items}
              caption={T.search.results}
              extra={(it) =>
                it.dossier_status !== "fetched" ? <FetchDetails item={it} onFetched={replaceItem} /> : null
              }
            />
          )}
          {result.unmatched.length > 0 ? (
            <div>
              <h3>{T.search.unmatched}</h3>
              <ul>
                {result.unmatched.map((u, i) => (
                  <li key={i}>
                    {[u.type_name, u.reg_no && u.reg_year ? `${u.reg_no}/${u.reg_year}` : null].filter(Boolean).join(" ")}
                    {u.pet_name || u.res_name ? ` — ${u.pet_name ?? "—"} vs ${u.res_name ?? "—"}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
