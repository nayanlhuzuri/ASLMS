"use client";

/**
 * Choose a Bench (design causelist-pdf-access, decision 2): the High Court publishes one cause list, and one original
 * PDF, per bench and list, so View Cause List with All Benches first asks which bench. A kit `Modal` with one sentence
 * and a `DataTable` (cards on phones) of the day's benches in the API's court order: Court, Judges, Lists, Entries and,
 * per bench with a list, View (the View Cause List modal on its Printed Entries) and Original PDF (the same modal on its
 * Original PDF tab, shown with `documents.view` or `documents.download` when some list of the bench has a stored PDF).
 * A bench that published nothing says so and has no buttons. The chooser is local state, not an address; choosing
 * closes it and opens the addressable modal. No request of its own: everything comes from `GET /causelists/{date}`.
 */
import { Button, DataTable, Modal, type Column } from "@/components/ui";
import type { CauselistBench } from "@/lib/api/types";
import { benchPdfState, type ViewTab } from "@/lib/causelist";
import { formatDate, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";

import s from "./causelist.module.css";

interface Row {
  key: string;
  bench: CauselistBench;
}

export function benchName(b: CauselistBench): string {
  return b.label ?? (b.bench_id !== null ? T.causelist.benchNumber(b.bench_id) : T.causelist.courtWide);
}

function listsText(b: CauselistBench): string {
  return b.lists
    .map((l) => {
      const name = T.causelist.listTypes[l.list_type] ?? l.list_type_text ?? l.list_type;
      return (l.version ?? 1) > 1 ? `${name} · ${T.causelist.corrected}` : name;
    })
    .join(", ");
}

export function BenchChooser({
  date,
  benches,
  canPdf,
  onChoose,
  onClose,
}: {
  date: string;
  benches: CauselistBench[];
  /** The reader holds `documents.view` or `documents.download`. */
  canPdf: boolean;
  onChoose: (bench: CauselistBench, tab: ViewTab) => void;
  onClose: () => void;
}) {
  const rows: Row[] = benches.map((bench, i) => ({ key: `${i}-${bench.bench_id ?? bench.lists[0]?.id ?? "none"}`, bench }));
  const columns: Column<Row>[] = [
    {
      key: "court",
      header: T.causelist.chooseCols.court,
      width: "96px",
      cell: (r) => r.bench.court_nos[0] ?? "—",
    },
    {
      key: "judges",
      header: T.causelist.chooseCols.judges,
      primary: true,
      rowHeader: true,
      cell: (r) => <span className={s.chooseJudges}>{benchName(r.bench)}</span>,
    },
    {
      key: "lists",
      header: T.causelist.chooseCols.lists,
      cell: (r) =>
        r.bench.lists.length > 0 ? listsText(r.bench) : <span className="muted">{T.causelist.noListPublishedLabel}</span>,
    },
    {
      key: "entries",
      header: T.causelist.chooseCols.entries,
      align: "right",
      cell: (r) => formatNumber(r.bench.entries),
    },
    {
      key: "actions",
      header: T.causelist.chooseCols.actions,
      cell: (r) => <ChooseActions bench={r.bench} canPdf={canPdf} onChoose={onChoose} />,
    },
  ];
  return (
    <Modal open title={T.causelist.chooseBenchTitle(formatDate(date))} onClose={onClose}>
      <div className="stack">
        <p>{T.causelist.chooseBenchIntro}</p>
        <DataTable caption={T.causelist.chooseTable} columns={columns} rows={rows} rowKey={(r) => r.key} />
      </div>
    </Modal>
  );
}

function ChooseActions({
  bench,
  canPdf,
  onChoose,
}: {
  bench: CauselistBench;
  canPdf: boolean;
  onChoose: (bench: CauselistBench, tab: ViewTab) => void;
}) {
  if (bench.lists.length === 0) return null;
  const pdf = benchPdfState(bench);
  const name = benchName(bench);
  return (
    <span className={s.chooseActions}>
      <Button variant="secondary" aria-label={T.causelist.chooseViewOf(name)} onClick={() => onChoose(bench, "entries")}>
        {T.causelist.chooseView}
      </Button>
      {canPdf && pdf === "available" ? (
        <Button variant="secondary" aria-label={T.causelist.choosePdfOf(name)} onClick={() => onChoose(bench, "pdf")}>
          {T.causelist.choosePdf}
        </Button>
      ) : (
        <span className="muted">{pdf === "pending" ? T.causelist.pdfPending : T.causelist.pdfNotAvailable}</span>
      )}
    </span>
  );
}
