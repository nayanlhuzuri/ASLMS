"use client";

import Link from "next/link";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Field, Select, TextInput } from "@/components/ui/Field";
import { Card, CardHead, PageHeader } from "@/components/ui/Layout";
import { Pagination } from "@/components/ui/Pagination";
import { Pill } from "@/components/ui/Pill";
import { Async, Empty, Loading } from "@/components/ui/States";
import { DataTable } from "@/components/ui/Table";
import { apiUrl } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtNumber, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { listTypeLabel, sourceLabel } from "@/lib/labels";
import type { CauseList, CauseListDate, Entry, Page } from "@/lib/types";
import { useUrlState } from "@/lib/urlState";

const SIZE = 100;

function resolutionPill(e: Entry) {
  if (e.case_id && e.resolution_status === "resolved") return null;
  if (e.resolution_status === "provisional") return <Pill tone="warning">Provisional</Pill>;
  if (e.resolution_status === "unresolved") return <Pill tone="muted">Not matched</Pill>;
  return null;
}

function Entries({ list }: { list: CauseList }) {
  const url = useUrlState();
  const q = url.get("q");
  const code = url.get("code");
  const page = Number(url.get("page", "1")) || 1;
  const [dq, setDq] = useState(q);
  const [dcode, setDcode] = useState(code);
  useEffect(() => {
    setDq(q);
    setDcode(code);
  }, [q, code]);
  const state = useApi<Page<Entry>>(`/causelists/${list.id}/entries`, { q: q || undefined, code: code || undefined, page, size: SIZE });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    url.set({ q: dq.trim(), code: dcode.trim(), page: null });
  };

  return (
    <Card labelledBy="entries-h">
      <CardHead
        id="entries-h"
        title={`${listTypeLabel(list.list_type)} list · ${fmtDate(list.list_date)}${list.label ? ` · ${list.label}` : ""}`}
        actions={
          list.document_id ? (
            <LinkButton href={apiUrl(`/causelists/${list.id}/pdf`)} external target="_blank" rel="noopener" icon="file" small>
              Open PDF<span className="sr-only"> (opens in a new tab)</span>
            </LinkButton>
          ) : null
        }
      />
      <form role="search" onSubmit={submit} style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Case number, party or CNR">
          <TextInput type="search" value={dq} onChange={(e) => setDq(e.target.value)} style={{ minWidth: 260 }} />
        </Field>
        <Field label="Counsel code">
          <TextInput value={dcode} onChange={(e) => setDcode(e.target.value)} placeholder="e.g. SC, EDU" className="mono" />
        </Field>
        <Button type="submit" icon="search">
          Filter
        </Button>
      </form>
      <Async state={state} loadingLabel="Loading entries">
        {(p) =>
          p.items.length === 0 ? (
            <Empty title="No entries match" />
          ) : (
            <>
              <DataTable
                bare
                caption="Cause-list entries"
                rows={p.items}
                rowKey={(r) => r.id}
                columns={[
                  { key: "sr", header: "Item", num: true, render: (r) => String((r.raw as { printed_sr?: unknown } | null)?.printed_sr ?? r.sr_no) },
                  { key: "court", header: "Court", render: (r) => r.court_no ?? "-" },
                  {
                    key: "case",
                    header: "Case",
                    render: (r) => (
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        {r.case_id ? (
                          <Link href={`/cases/${r.case_id}`} className="mono" style={{ fontWeight: 500 }}>
                            {r.case_no_text ?? r.cnr ?? "Open case"}
                          </Link>
                        ) : (
                          <span className="mono">{r.case_no_text ?? "-"}</span>
                        )}
                        {resolutionPill(r)}
                      </div>
                    ),
                  },
                  {
                    key: "parties",
                    header: "Parties",
                    render: (r) => (
                      <span>
                        {r.petitioner_text ?? "-"}
                        <span className="muted"> vs. </span>
                        {r.respondent_text ?? "-"}
                      </span>
                    ),
                  },
                  {
                    key: "adv",
                    header: "Advocates",
                    render: (r) => (
                      <span style={{ fontSize: 13 }}>
                        {r.pet_advocate_text ?? "-"}
                        <br />
                        <span className="muted">{r.res_advocate_text ?? "-"}</span>
                      </span>
                    ),
                  },
                  { key: "codes", header: "Codes", mono: true, render: (r) => r.counsel_codes.join("; ") || "-" },
                ]}
              />
              <Pagination page={p.page} size={p.size} total={p.total} onPage={(n) => url.set({ page: n > 1 ? n : null })} noun="entries" />
            </>
          )
        }
      </Async>
    </Card>
  );
}

function CauseListsInner() {
  const url = useUrlState();
  const dates = useApi<CauseListDate[]>("/causelists/dates", { limit: 90 });
  const date = url.get("date") || dates.data?.[0]?.date || "";
  const lists = useApi<CauseList[]>(date ? "/causelists" : null, { date });
  const listId = url.get("list");
  const selected = lists.data?.find((l) => l.id === listId);

  return (
    <>
      <PageHeader title="Cause Lists" sub="Daily, supplementary and Lawazima lists of the Gauhati High Court, as collected." />
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="Date">
          <Select value={date} onChange={(e) => url.set({ date: e.target.value, list: null, q: null, code: null, page: null })} style={{ minWidth: 260 }}>
            {dates.data && !dates.data.some((d) => d.date === date) && date ? <option value={date}>{fmtDate(date)}</option> : null}
            {(dates.data ?? []).map((d) => (
              <option key={d.date} value={d.date}>
                {fmtDate(d.date)} · {d.lists} {d.lists === 1 ? "list" : "lists"}, {fmtNumber(d.entries)} entries
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Or pick a date">
          <TextInput type="date" value={date} onChange={(e) => e.target.value && url.set({ date: e.target.value, list: null, q: null, code: null, page: null })} />
        </Field>
      </div>
      {dates.data && dates.data.length === 0 && !url.get("date") ? (
        <Empty title="No cause lists collected yet" center>
          Lists appear after the daily data cycle has run.
        </Empty>
      ) : date ? (
        <Async state={lists} loadingLabel="Loading lists">
          {(ls) =>
            ls.length === 0 ? (
              <Empty title={`No lists stored for ${fmtDate(date)}`} />
            ) : (
              <DataTable
                caption={`Cause lists for ${fmtDate(date)}`}
                rows={ls}
                rowKey={(l) => l.id}
                columns={[
                  {
                    key: "type",
                    header: "List",
                    render: (l) => (
                      <button
                        type="button"
                        onClick={() => url.set({ list: l.id, q: null, code: null, page: null })}
                        aria-pressed={l.id === listId}
                        style={{ background: "none", border: "none", padding: 0, color: "var(--accent)", fontWeight: 600, cursor: "pointer", minHeight: 36, textAlign: "left" }}
                      >
                        {listTypeLabel(l.list_type)}
                        {l.label ? ` · ${l.label}` : ""}
                      </button>
                    ),
                  },
                  { key: "bench", header: "Bench", mono: true, render: (l) => l.bench_id },
                  { key: "source", header: "Source", render: (l) => sourceLabel(l.source) },
                  { key: "entries", header: "Entries", num: true, render: (l) => fmtNumber(l.entry_count) },
                  {
                    key: "parse",
                    header: "Parse",
                    render: (l) => (
                      <Pill tone={l.parse_status === "parsed" || l.parse_status === "not_applicable" ? "success" : l.parse_status === "failed" ? "criticalSoft" : "warning"}>
                        {humanize(l.parse_status)}
                      </Pill>
                    ),
                  },
                  { key: "fetched", header: "Fetched", render: (l) => fmtDateTime(l.fetched_at) },
                  {
                    key: "pdf",
                    header: "",
                    actions: true,
                    render: (l) =>
                      l.document_id ? (
                        <a href={apiUrl(`/causelists/${l.id}/pdf`)} target="_blank" rel="noopener" style={{ fontWeight: 600, fontSize: 14 }}>
                          Open PDF<span className="sr-only"> (opens in a new tab)</span>
                        </a>
                      ) : null,
                  },
                ]}
              />
            )
          }
        </Async>
      ) : dates.loading ? (
        <Loading />
      ) : null}
      {selected ? <Entries list={selected} /> : null}
    </>
  );
}

export default function CauseListsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <CauseListsInner />
    </Suspense>
  );
}
