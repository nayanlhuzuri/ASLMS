"use client";

/**
 * The remarks history (design case-workspace-admin, decisions 15 and 16; owner decision 3: every past remark and comment
 * can be reached from the case page): a wide side panel titled "Remarks and notes" on the URL overlay `?remarks=all`,
 * with two tabs.
 * - "Remarks (n)": every movement, newest first (`GET /cases/{ref}/custody?order=desc`, 50 at a time with "Show
 *   more"): the date in a `DateChip`, who moved the case to whom, the action asked, the due date and the full remark,
 *   only when the API returned it. When `remarks_shown` is false the panel says once that remarks are shown only to the
 *   people working on the case; the frontend never infers a hidden remark.
 * - "Notes (m)": the notes trail in order (by `seq_no`, as the Notes tab; `include_superseded=true`, 50 at a time),
 *   with a kind filter (the API's `kind`); a correction shows the note it corrects folded under it, a superseded note
 *   links to its correction. Notes the caller cannot read are never listed (the API's note rule); no drafts.
 * Nothing in the panel writes.
 */
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useId, useState, type KeyboardEvent } from "react";

import { Badge, Button, Collapsible, DateChip, EmptyState, ErrorBanner, ListRow, Loading, Notice, SelectField, SidePanel } from "@/components/ui";
import { api } from "@/lib/api/client";
import { caseKey, useMe, useWorkflowCodes } from "@/lib/api/hooks";
import type { CaseDetail, CustodyHistory, CustodyLeg, Note, NoteList } from "@/lib/api/types";
import { legActor, legHolder, withText } from "@/lib/cases";
import { formatDate, formatDateTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { apiCasePath, refPath } from "@/lib/refs";

import { NoteAttachments } from "./Notes";
import s from "./remarks.module.css";

export const REMARKS_PAGE = 50;

type PanelTab = "remarks" | "notes";

function loaded<T>(pages: { items?: T[]; legs?: T[] }[] | undefined, key: "items" | "legs"): T[] {
  return (pages ?? []).flatMap((p) => (p[key] as T[] | undefined) ?? []);
}

/** The movements newest first, 50 at a time. */
export function useRemarks(caseRef: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: [...caseKey(caseRef), "custody", "desc", "all"],
    queryFn: ({ pageParam }) =>
      api<CustodyHistory>(apiCasePath(caseRef, "custody"), { query: { order: "desc", limit: REMARKS_PAGE, offset: pageParam } }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const n = all.reduce((sum, p) => sum + p.legs.length, 0);
      return n < last.total && last.legs.length > 0 ? n : undefined;
    },
    enabled,
  });
}

/** The notes trail in order, every kind or one, corrected notes included. */
export function useNotesTrail(caseRef: string, kind: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: [...caseKey(caseRef), "notes", "all", kind],
    queryFn: ({ pageParam }) =>
      api<NoteList>(`${apiCasePath(caseRef)}/notes`, {
        query: { include_superseded: true, kind: kind || undefined, limit: REMARKS_PAGE, offset: pageParam },
      }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => {
      const n = all.reduce((sum, p) => sum + p.items.length, 0);
      return n < last.total && last.items.length > 0 ? n : undefined;
    },
    enabled,
  });
}

/** Decision 15's heading of one movement. */
export function legHeading(leg: CustodyLeg, meId?: string | null): string {
  const to = withText(legHolder(leg), meId).text;
  const actor = legActor(leg);
  const by = actor ? withText(actor).text : "—";
  if (leg.reason === "sent") return T.remarks.sentHeading(by, to);
  if (leg.reason === "recalled") return T.remarks.recalledHeading(by);
  return T.remarks.otherHeading(leg.reason_label, by, to);
}

function RemarkEntry({ leg, meId }: { leg: CustodyLeg; meId: string | null }) {
  return (
    <ListRow as="li" lead={<DateChip date={leg.started_at} />}>
      <div className={s.entry}>
        <div className={s.when}>{formatDateTime(leg.started_at)}</div>
        <div className={s.heading}>{legHeading(leg, meId)}</div>
        <div>{T.remarks.actionAsked(leg.pending_action_label)}</div>
        <div className="muted">{leg.due_date ? T.remarks.dueBy(formatDate(leg.due_date)) : T.remarks.noDue}</div>
        {leg.remark ? <div className={s.full}>{leg.remark}</div> : null}
      </div>
    </ListRow>
  );
}

function RemarksTab({ query, meId }: { query: ReturnType<typeof useRemarks>; meId: string | null }) {
  const legs = loaded<CustodyLeg>(query.data?.pages, "legs");
  const shown = query.data?.pages[0]?.remarks_shown ?? true;
  return (
    <div className="stack">
      {query.isPending ? <Loading /> : null}
      <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
      {query.data && !shown ? <Notice>{T.remarks.onlyWorking}</Notice> : null}
      {query.data ? (
        legs.length === 0 ? (
          <EmptyState>{T.remarks.noRemarks}</EmptyState>
        ) : (
          <ol className={s.list} aria-label={T.remarks.remarksTab(query.data.pages[0]?.total ?? legs.length)}>
            {legs.map((leg) => (
              <RemarkEntry key={leg.seq_no} leg={leg} meId={meId} />
            ))}
          </ol>
        )
      ) : null}
      {query.hasNextPage ? (
        <div>
          <Button variant="secondary" busy={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            {T.remarks.showMore}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function noteAnchor(seq: number): string {
  return `remarks-note-${seq}`;
}

function NoteHead({ n }: { n: Note }) {
  const author = withText({ designation: n.author.designation, office: n.author.office_code, name: n.author.name });
  return (
    <div className={s.noteHead}>
      <Badge>{n.kind_label}</Badge>
      <span className="mono muted">{n.ref_no}</span>
      <span title={author.title}>{author.text}</span>
      <span className="muted">{formatDateTime(n.created_at)}</span>
      <Badge>{T.case.visibilities[n.visibility] ?? n.visibility}</Badge>
    </div>
  );
}

/** The corrected note, from the loaded page, else fetched once the fold opens (`GET /notes/{note}`). */
function CorrectedBody({ refNo, fromPage }: { refNo: string; fromPage: Note | undefined }) {
  const one = useQuery({
    queryKey: ["note", refPath(refNo)],
    queryFn: () => api<Note>(`/notes/${encodeURIComponent(refPath(refNo))}`),
    enabled: !fromPage,
  });
  const n = fromPage ?? one.data;
  if (!n) {
    return (
      <>
        {one.isPending ? <Loading lines={2} /> : null}
        <ErrorBanner error={one.error} />
      </>
    );
  }
  return (
    <div className={s.corrected} aria-label={T.remarks.correctedNote}>
      <div className={s.correctedLabel}>{T.remarks.correctedNote}</div>
      <NoteHead n={n} />
      <div className={s.full}>{n.body}</div>
      <NoteAttachments note={n} />
    </div>
  );
}

function NoteEntry({ n, bySeq }: { n: Note; bySeq: Map<number, Note> }) {
  return (
    <li id={noteAnchor(n.seq_no)} className={s.note}>
      <NoteHead n={n} />
      {n.supersedes ? <div className="muted">{T.remarks.corrects(n.supersedes.ref_no)}</div> : null}
      {n.superseded_by ? (
        <div>
          <Badge tone="warning">
            <a href={`#${noteAnchor(n.superseded_by.seq_no)}`}>{T.remarks.correctedBy(n.superseded_by.ref_no)}</a>
          </Badge>
        </div>
      ) : null}
      <div className={s.full}>{n.body}</div>
      <NoteAttachments note={n} />
      {n.supersedes ? (
        <Collapsible summary={T.remarks.showCorrected}>
          <CorrectedBody refNo={n.supersedes.ref_no} fromPage={bySeq.get(n.supersedes.seq_no)} />
        </Collapsible>
      ) : null}
    </li>
  );
}

function NotesTab({
  query,
  kind,
  onKind,
}: {
  query: ReturnType<typeof useNotesTrail>;
  kind: string;
  onKind: (kind: string) => void;
}) {
  const codes = useWorkflowCodes();
  const notes = loaded<Note>(query.data?.pages, "items");
  const bySeq = new Map(notes.map((n) => [n.seq_no, n]));
  const kinds = (codes.data?.note_kinds ?? []).filter((k) => k.selectable).map((k) => ({ value: k.code, label: k.label }));
  return (
    <div className="stack">
      <div className={s.filters}>
        <SelectField
          label={T.remarks.kind}
          placeholder={T.remarks.allKinds}
          options={kinds}
          value={kind}
          onChange={(e) => onKind(e.target.value)}
        />
      </div>
      {query.isPending ? <Loading /> : null}
      <ErrorBanner error={query.error} onRetry={() => query.refetch()} />
      {query.data ? (
        notes.length === 0 ? (
          <EmptyState>{T.remarks.noNotes}</EmptyState>
        ) : (
          <ol className={s.list} aria-label={T.remarks.notesTab(query.data.pages[0]?.total ?? notes.length)}>
            {notes.map((n) => (
              <NoteEntry key={n.id} n={n} bySeq={bySeq} />
            ))}
          </ol>
        )
      ) : null}
      {query.hasNextPage ? (
        <div>
          <Button variant="secondary" busy={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            {T.remarks.showMore}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** Two tabs inside the panel (`role="tablist"`, the arrow keys move between them). */
function PanelTabs({
  tab,
  onTab,
  labels,
  ids,
}: {
  tab: PanelTab;
  onTab: (tab: PanelTab) => void;
  labels: Record<PanelTab, string>;
  ids: Record<PanelTab, { tab: string; panel: string }>;
}) {
  const order: PanelTab[] = ["remarks", "notes"];
  function onKey(e: KeyboardEvent<HTMLButtonElement>) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = order[(order.indexOf(tab) + 1) % order.length]!;
    onTab(next);
    document.getElementById(ids[next].tab)?.focus();
  }
  return (
    <div role="tablist" aria-label={T.remarks.tabs} className={s.tabs}>
      {order.map((t) => (
        <button
          key={t}
          id={ids[t].tab}
          type="button"
          role="tab"
          aria-selected={tab === t}
          aria-controls={ids[t].panel}
          tabIndex={tab === t ? 0 : -1}
          className={tab === t ? `${s.tab} ${s.tabOn}` : s.tab}
          onClick={() => onTab(t)}
          onKeyDown={onKey}
        >
          {labels[t]}
        </button>
      ))}
    </div>
  );
}

export function RemarksPanel({
  caseRef,
  c,
  open,
  onClose,
}: {
  caseRef: string;
  c: Pick<CaseDetail, "counts">;
  open: boolean;
  onClose: () => void;
}) {
  const me = useMe();
  const [tab, setTab] = useState<PanelTab>("remarks");
  const [kind, setKind] = useState("");
  const base = useId();
  const remarks = useRemarks(caseRef, open);
  const notes = useNotesTrail(caseRef, kind, open && tab === "notes");
  const remarksTotal = remarks.data?.pages[0]?.total ?? null;
  const notesTotal = notes.data?.pages[0]?.total ?? (kind ? null : (c.counts.notes ?? null));
  const ids = {
    remarks: { tab: `${base}-tab-remarks`, panel: `${base}-panel-remarks` },
    notes: { tab: `${base}-tab-notes`, panel: `${base}-panel-notes` },
  };
  return (
    <SidePanel open={open} title={T.remarks.title} onClose={onClose} wide>
      <div className="stack">
        <PanelTabs
          tab={tab}
          onTab={setTab}
          ids={ids}
          labels={{
            remarks: T.remarks.remarksTab(remarksTotal),
            notes: T.remarks.notesTab(notesTotal),
          }}
        />
        <div role="tabpanel" id={ids.remarks.panel} aria-labelledby={ids.remarks.tab} hidden={tab !== "remarks"}>
          {tab === "remarks" ? <RemarksTab query={remarks} meId={me.data?.user.id ?? null} /> : null}
        </div>
        <div role="tabpanel" id={ids.notes.panel} aria-labelledby={ids.notes.tab} hidden={tab !== "notes"}>
          {tab === "notes" ? <NotesTab query={notes} kind={kind} onKind={setKind} /> : null}
        </div>
      </div>
    </SidePanel>
  );
}
