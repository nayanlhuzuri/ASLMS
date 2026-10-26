"use client";

/**
 * "View Cause List" (design portal-ui-polish-2, decision 25): the chosen bench's list in the kit's large `Modal` over the
 * Cause List page (full screen on phones), titled "Cause List: ‹bench› · ‹date›" with the bench's list types as the
 * facts. Its address is `?view=<bench_id>&vtab=entries|pdf` (a court-wide file, which has no bench id, is named by its
 * list id), opened through `useUrlOverlay`, so Back closes it and a shared link reopens it; a tab change replaces the
 * address, so Back still closes the modal. Two tabs:
 * - Printed Entries: the bench's entries in court order from `GET /causelists/{date}/entries`, paged by 100, as
 *   printed (court and item in the leading column, then the case, the parties, the advocates and the section), each with
 *   the page's recommendation or owner badges, the case linked to its page when the caller can open it. Claim stays on
 *   the page.
 * - Original PDF: a list chooser when the bench has more than one list, then the court's PDF in the browser's own viewer
 *   (`documents.view`) and Download (`documents.download`); without either function the tab says so. The file is first
 *   asked for and dropped once its head arrives, so a `no_pdf` or `file_missing` answer shows the API's message.
 * No new API: every row and fact comes from the server, which applies the visibility rules.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, buttonClass, DataTable, EmptyState, ErrorBanner, Lead, Loading, Modal, Notice, Pagination, SelectField, Tabs, type Column } from "@/components/ui";
import { ApiError, probeFile } from "@/lib/api/client";
import { useCauselistEntries } from "@/lib/api/hooks";
import type { Causelist, CauselistBench, CauselistEntry } from "@/lib/api/types";
import { VIEW_PAGE, viewQuery, viewValue, type ViewTab } from "@/lib/causelist";
import { canViewInline } from "@/lib/documents";
import { formatDate } from "@/lib/format";
import { T } from "@/lib/messages";

import { CaseCell, caseNo, Parties } from "./EntryTable";
import { listFileUrl } from "./ListStrip";
import { OwnershipCell } from "./OwnershipCell";
import s from "./causelist.module.css";

function benchName(b: CauselistBench): string {
  return b.label ?? (b.bench_id !== null ? T.causelist.benchNumber(b.bench_id) : T.causelist.courtWide);
}

function listName(l: Causelist): string {
  return T.causelist.listTypes[l.list_type] ?? l.list_type_text ?? l.list_type;
}

export function ViewCauseList({
  date,
  bench,
  initialTab,
  names,
  canView,
  canDownload,
  hrefOf,
  onClose,
}: {
  date: string;
  bench: CauselistBench;
  initialTab: ViewTab;
  names: Record<string, string>;
  canView: boolean;
  canDownload: boolean;
  /** The address of the modal on a tab. */
  hrefOf: (tab: ViewTab) => string;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<ViewTab>(initialTab);

  function select(next: ViewTab) {
    setTab(next);
    // the tab lives in the address without a new history entry, so Back still closes the modal
    window.history.replaceState(window.history.state, "", hrefOf(next));
  }

  const tabs: { key: ViewTab; label: string }[] = [
    { key: "entries", label: T.causelist.printedTab },
    { key: "pdf", label: T.causelist.pdfTab },
  ];
  return (
    <Modal
      open
      title={T.causelist.viewTitle(benchName(bench), formatDate(date))}
      onClose={onClose}
      header={
        <div className="stack">
          <div className={s.badges}>
            {bench.lists.map((l) => (
              <Badge key={l.id}>{listName(l)}</Badge>
            ))}
          </div>
          <Tabs
            label={T.causelist.viewTabs}
            items={tabs.map((t) => ({ href: hrefOf(t.key), label: t.label, active: tab === t.key }))}
            onSelect={(href) => select(tabs.find((t) => hrefOf(t.key) === href)?.key ?? "entries")}
          />
        </div>
      }
    >
      {tab === "pdf" ? (
        <PdfTab bench={bench} canView={canView} canDownload={canDownload} />
      ) : (
        <PrintedEntries date={date} bench={bench} names={names} />
      )}
    </Modal>
  );
}

function PrintedEntries({ date, bench, names }: { date: string; bench: CauselistBench; names: Record<string, string> }) {
  const [offset, setOffset] = useState(0);
  const entries = useCauselistEntries(date, viewQuery(viewValue(bench), offset));
  const columns: Column<CauselistEntry>[] = [
    {
      key: "item",
      header: T.causelist.courtItem,
      primary: true,
      width: "calc(var(--lead-w) + var(--s6))",
      cell: (e) => (
        <Lead>
          <span className={s.courtItem}>{T.causelist.courtItemText(e.court_no, e.is_connected ? null : e.printed_sr_no)}</span>
        </Lead>
      ),
    },
    {
      key: "case",
      header: T.causelist.case,
      cell: (e) => (
        <>
          {e.is_connected ? <div className={s.connected}>{e.with_text ?? T.causelist.connectedFallback}</div> : null}
          <CaseCell e={e} />
        </>
      ),
    },
    { key: "parties", header: T.causelist.parties, cell: (e) => <Parties e={e} /> },
    {
      key: "advocates",
      header: T.causelist.advocates,
      cell: (e) => (
        <div className={s.pre}>
          <div>{e.pet_advocate_text ?? "—"}</div>
          <div>{e.res_advocate_text ?? "—"}</div>
        </div>
      ),
    },
    { key: "section", header: T.causelist.section, cell: (e) => e.section ?? "—" },
    { key: "ownership", header: T.causelist.ownership, cell: (e) => <OwnershipCell entry={e} names={names} /> },
  ];
  return (
    <div className="stack">
      <ErrorBanner error={entries.error} onRetry={() => entries.refetch()} />
      {entries.isPending ? <Loading /> : null}
      {entries.data ? (
        <>
          <DataTable
            caption={T.causelist.table}
            columns={columns}
            rows={entries.data.items}
            rowKey={(e) => e.id}
            rowLabel={(e) => caseNo(e)}
            empty={<EmptyState>{T.causelist.noEntries}</EmptyState>}
          />
          <Pagination offset={offset} limit={VIEW_PAGE} total={entries.data.total} onChange={setOffset} />
        </>
      ) : null}
    </div>
  );
}

function PdfTab({ bench, canView, canDownload }: { bench: CauselistBench; canView: boolean; canDownload: boolean }) {
  const [chosen, setChosen] = useState(bench.lists[0]?.id ?? "");
  const list = bench.lists.find((l) => l.id === chosen) ?? bench.lists[0];
  if (!canView && !canDownload) return <Notice>{T.causelist.pdfNeedsFunction}</Notice>;
  if (!list) return <p className="muted">{T.causelist.noListPublished}</p>;
  return (
    <div className="stack">
      {bench.lists.length > 1 ? (
        <div className={s.bar}>
          <SelectField
            label={T.causelist.chooseList}
            value={list.id}
            options={bench.lists.map((l) => ({
              value: l.id,
              label: (l.version ?? 1) > 1 ? `${listName(l)} · ${T.causelist.corrected}` : listName(l),
            }))}
            onChange={(e) => setChosen(e.target.value)}
          />
        </div>
      ) : null}
      {list.has_pdf ? (
        <PdfView key={list.id} list={list} canView={canView} canDownload={canDownload} />
      ) : (
        <p className="muted">{list.fetch_status === "pending" ? T.causelist.pdfPending : T.causelist.noPdf}</p>
      )}
    </div>
  );
}

function PdfView({ list, canView, canDownload }: { list: Causelist; canView: boolean; canDownload: boolean }) {
  const disposition = canView ? "inline" : "attachment";
  const probe = useQuery({
    queryKey: ["causelist-file", list.id, disposition],
    queryFn: () =>
      probeFile(`/causelists/lists/${encodeURIComponent(list.id)}/file`, { query: { disposition } }).then(() => true),
    retry: false,
    staleTime: 60_000,
  });
  if (probe.isPending) return <p className="muted">{T.causelist.pdfCheckingNote}</p>;
  if (probe.error) {
    const e = probe.error;
    if (e instanceof ApiError && (e.code === "no_pdf" || e.code === "file_missing")) return <Notice tone="warning">{e.message}</Notice>;
    return <ErrorBanner error={e} onRetry={() => probe.refetch()} />;
  }
  const inline = canView && canViewInline("application/pdf");
  return (
    <div className="stack">
      {canDownload ? (
        <div className={s.pdfToolbar}>
          <a className={buttonClass("secondary")} href={listFileUrl(list.id, "attachment")} download>
            {T.causelist.download}
          </a>
        </div>
      ) : null}
      {inline ? <iframe className={s.pdfFrame} src={listFileUrl(list.id, "inline")} title={T.causelist.pdfFrame(listName(list))} /> : null}
      {canView && !inline ? (
        <a href={listFileUrl(list.id, "inline")} target="_blank" rel="noopener noreferrer">
          {T.causelist.view}
        </a>
      ) : null}
    </div>
  );
}

