"use client";

/**
 * The Case Assistant (design assistant, decision 14; the template's Assistant tab and Assistant page):
 * - the banner of the mode (preview: a warning notice; sourcetrace: the reminder to check sources);
 * - the scope switch: This case | My cases | All court orders on the case tab (starting on This case), My cases | All
 *   court orders on the page, with a line under the question box naming what is searched (owner, 23 Oct 2026).
 *   Switching the scope opens that scope's latest conversation and searches the last question again there;
 * - the conversation in a box of fixed height with its own scroll bar, keyboard-focusable and labelled
 *   "Conversation": a new answer scrolls it to the newest message, choosing an older answer keeps the position
 *   (owner, 23 Oct 2026);
 * - each answer a card with its outcome in words, a "Preview" badge from the message's own mode, the text, and its
 *   sources: in the "Sources used" side panel from 1280 px, under the answer below it; related orders of other cases
 *   grouped apart; a source opens the file route at its page, or the court-record view for a case the reader cannot
 *   open;
 * - suggested questions on an empty thread fill the question box; the composer counts characters and the questions
 *   left this hour; Ask is the screen's one primary on the page (secondary on the case tab, whose header holds the
 *   case's primary); New conversation and Copy to note are secondary. Copy to note shows on a case-scope answer when
 *   the case allows a note, and fills the note dialog with the answer and its references.
 * Every refusal and failure is in words (`ASSISTANT_ERRORS`, `ASSISTANT_FAILURES`). The API decides everything.
 *
 * Design assistant-ollama (round 1, decision 14), in ollama mode: the local-model banner; "Court information only" by
 * default everywhere; on the case tab only, and only for a reader holding the case page's read guard, the secondary
 * "Include This Case's Internal Records" with its confirmation, then the "Internal Records of This Case Included"
 * banner with "Start a Court-Only Conversation" (a new conversation) and the mark "Internal records included from
 * here" in the thread; the suggestion line on an answer flagged `suggest_internal` (it does nothing without the click);
 * each answer's Local Model badge and model name, its `[S#]` markers linking to their sources, the Court Record and
 * Internal Records groups with the uncited sources apart, "Text Given to the Model", the removed-reference and
 * cut-short lines; the readiness notices; Copy to note preset to the narrowest visibility of the cited internal records
 * with its warning. The server decides what is read; nothing here widens it.
 *
 * Design assistant-polish: Enter sends and Shift+Enter starts a new line, with the hint under the box (decision 1); an
 * answer with labelled citations (a local model's, or a quick fact from the case record) lists no sources: each `[S#]`
 * marker is a button opening that one source in a dialog, and "Sources (n)" opens the full list in another; answers
 * without markers (preview, SourceTrace) keep their list under the answer; the side panel is gone (decision 16); a quick
 * fact carries "From the Case Record", read from `engine.kind` (decision 15); Copy to note names each cited source by
 * its own label (decision 17).
 *
 * Design assistant-ollama-work: the case tab is about its own case only (This Case, with no scope switch) and says where
 * to ask across cases, about one's own work or across all court orders, with the link "Open the Assistant" (decision
 * 1); the page has the kit `Tabs` My Work, My Cases and All Court Orders in the address (`?tab=`), each listing its own
 * conversations, and switching tabs asks nothing again (decision 2). A My Work answer is the server's count first, its
 * rows in a `DataTable` with case links, "as of", "Open the Full List" and the badge "From Your Lists"; it carries no
 * markers, Sources or Copy to Note (decision 4). A My Cases or All Court Orders answer flagged `suggest_work` offers "Ask
 * in My Work", which asks the same question there in a new conversation, only on the click (decision 11).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  buttonClass,
  Card,
  CharCounter,
  Chip,
  ChipGroup,
  ConfirmDialog,
  cx,
  DataTable,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  OfficeName,
  PageHeader,
  Tabs,
  TextArea,
  useToast,
  type Column,
} from "@/components/ui";
import type { NoteMode } from "@/components/workflow/NoteComposer";
import { NoteDialog } from "@/components/workflow/NoteDialog";
import { api } from "@/lib/api/client";
import { useCase, useMe } from "@/lib/api/hooks";
import type {
  AssistantAsk,
  AssistantCitation,
  AssistantConversationList,
  AssistantInternal,
  AssistantMessage,
  AssistantScope,
  AssistantStatus,
  AssistantThread,
} from "@/lib/api/types";
import {
  groupSources,
  hasLabels,
  highlights,
  isCaseRecord,
  isInternal,
  isWorkAnswer,
  kindLabel,
  markerName,
  markers,
  narrowestVisibility,
  noteText,
  openWords,
  otherCaseName,
  PAGE_TABS,
  pageScopes,
  questionOf,
  questionsLeft,
  scopeForTab,
  sourceId,
  sourceLink,
  sourceWords,
  switchedBefore,
  tabHref,
  workColumns,
  workValue,
} from "@/lib/assistant";
import { canAny } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { ASSISTANT_ERRORS, ASSISTANT_FAILURES, T } from "@/lib/messages";
import { CASE_READERS, showsAssistant } from "@/lib/routes";
import { labelFor, serverLabel } from "@/lib/displayLabels";

import s from "./assistant.module.css";

const A = T.assistant;
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export const STATUS_KEY = ["assistant", "status"] as const;

export function useAssistantStatus(enabled = true) {
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: () => api<AssistantStatus>("/assistant/status"),
    enabled,
  });
}

function threadKey(id: string) {
  return ["assistant", "thread", id] as const;
}

function listKey(screen: "case" | "page", scope: AssistantScope, caseRef: string | null) {
  return ["assistant", "conversations", screen, scope, caseRef ?? ""] as const;
}

/** The caller's conversations of a scope, newest first: the latest only on the case tab, 50 on the page. */
function fetchList(screen: "case" | "page", scope: AssistantScope, caseRef: string | null) {
  return api<AssistantConversationList>("/assistant/conversations", {
    query: { scope, case: caseRef ?? undefined, limit: screen === "page" ? 50 : 1 },
  });
}

/** The banner of every Assistant screen (decision 14). */
export function AssistantBanner({ status }: { status: AssistantStatus | undefined }) {
  if (!status) return null;
  if (status.state === "preview") return <Notice tone="warning">{A.previewBanner}</Notice>;
  if (status.state === "ready" && status.mode === "ollama") return <Notice>{A.ollamaBanner}</Notice>;
  if (status.state === "ready") return <Notice>{A.sourcetraceBanner}</Notice>;
  return null;
}

/** The local model's readiness in words (decision 13): a notice while it starts or when it cannot be reached. */
function ReadinessNotice({ status }: { status: AssistantStatus | undefined }) {
  const readiness = status?.engine?.readiness;
  if (readiness === "loading") return <Notice tone="warning">{A.loadingNotice}</Notice>;
  if (readiness === "unavailable") return <Notice tone="warning">{A.unavailableNotice}</Notice>;
  return null;
}

/** "Text Given to the Model" under a local-model source (decision 9: re-rendered by the server at read time). Under a
 * quick fact (`record`) no model was called: the block reads "Facts From the Case Record" and is shown open, the
 * evidence of every value the answer states (design assistant-polish-followups, decision 2). */
function TextGiven({ c, record = false }: { c: AssistantCitation; record?: boolean }) {
  if (!c.label) return null;
  return (
    <details className={s.given} open={record || undefined}>
      <summary>{record ? A.factsUsed : A.textGiven}</summary>
      {c.context ? <pre className={s.givenText}>{c.context}</pre> : <p className={s.hint}>{A.noTextGiven}</p>}
    </details>
  );
}

function Passage({ text }: { text: string | null | undefined }) {
  if (!text) return null;
  return (
    <blockquote className={s.passage}>
      “
      {highlights(text).map((seg, i) => (seg.hit ? <mark key={i}>{seg.text}</mark> : <span key={i}>{seg.text}</span>))}
      ”
    </blockquote>
  );
}

function SourceItem({
  c,
  n,
  messageId,
  currentCaseId,
  record = false,
}: {
  c: AssistantCitation;
  n: number;
  messageId: string;
  currentCaseId?: string | null;
  record?: boolean;
}) {
  const id = sourceId(messageId, c.label, n);
  const num = c.label ?? String(n);
  if (!c.available) {
    // the API names nothing of a source the reader can no longer reach (no type, date, page or case)
    return (
      <li className={s.source} id={id}>
        <span className={s.num} aria-hidden="true">
          {num}
        </span>
        <div className={s.sourceBody}>
          <span className={s.muted}>{A.unavailable}</span>
        </div>
      </li>
    );
  }
  const link = sourceLink(c, messageId);
  const other = otherCaseName(c, currentCaseId);
  const title = sourceWords(c);
  return (
    <li className={s.source} id={id}>
      <span className={s.num} aria-hidden="true">
        {num}
      </span>
      <div className={s.sourceBody}>
        {c.label ? (
          <span className={s.kindLine}>
            {kindLabel(c)}
            {isInternal(c) ? <Badge tone="warning">{A.internalBadge}</Badge> : null}
          </span>
        ) : null}
        {link ? (
          link.newTab ? (
            <a className={s.sourceTitle} href={link.href} target="_blank" rel="noopener noreferrer" aria-label={`${A.openSource(n)}: ${title}`}>
              {title}
            </a>
          ) : (
            <Link className={s.sourceTitle} href={link.href} aria-label={`${A.openSource(n)}: ${title}`}>
              {title}
            </Link>
          )
        ) : (
          <span className={s.sourceTitle}>{title}</span>
        )}
        {other ? <span className="cno muted">{other}</span> : null}
        <Passage text={c.passage} />
        <TextGiven c={c} record={record} />
      </div>
    </li>
  );
}

function Items({
  items,
  m,
  currentCaseId,
  label,
}: {
  items: { c: AssistantCitation; n: number }[];
  m: AssistantMessage;
  currentCaseId?: string | null;
  label?: string;
}) {
  if (!items.length) return null;
  return (
    <ul className={s.sources} aria-label={label}>
      {items.map(({ c, n }) => (
        <SourceItem key={`${m.id}-${n}`} c={c} n={n} messageId={m.id} currentCaseId={currentCaseId} record={isCaseRecord(m)} />
      ))}
    </ul>
  );
}

/** A local model's sources (decision 8): cited ones grouped Court Record and Internal Records, the rest collapsed. */
function LocalSourceList({ m, currentCaseId }: { m: AssistantMessage; currentCaseId?: string | null }) {
  const g = groupSources(m.citations.map((c, i) => ({ c, n: i + 1 })));
  return (
    <>
      {g.court.length ? <p className={s.group}>{A.courtGroup}</p> : null}
      <Items items={g.court} m={m} currentCaseId={currentCaseId} label={A.courtGroup} />
      {g.internal.length ? <p className={s.group}>{A.internalGroup}</p> : null}
      <Items items={g.internal} m={m} currentCaseId={currentCaseId} label={A.internalGroup} />
      {g.uncited.length ? (
        <details className={s.uncited}>
          <summary>{A.uncited}</summary>
          <Items items={g.uncited} m={m} currentCaseId={currentCaseId} label={A.uncited} />
        </details>
      ) : null}
    </>
  );
}

/** The sources of one answer, the related orders of other cases apart (decision 14). */
function SourceList({ m, currentCaseId }: { m: AssistantMessage; currentCaseId?: string | null }) {
  if (m.mode === "ollama") return <LocalSourceList m={m} currentCaseId={currentCaseId} />;
  const own = m.citations.map((c, i) => ({ c, n: i + 1 })).filter((x) => !x.c.related);
  const related = m.citations.map((c, i) => ({ c, n: i + 1 })).filter((x) => x.c.related);
  return (
    <>
      {own.length ? (
        <ul className={s.sources}>
          {own.map(({ c, n }) => (
            <SourceItem key={`${m.id}-${n}`} c={c} n={n} messageId={m.id} currentCaseId={currentCaseId} record={isCaseRecord(m)} />
          ))}
        </ul>
      ) : null}
      {related.length ? (
        <>
          <p className={s.group}>{A.related}</p>
          <ul className={s.sources} aria-label={A.related}>
            {related.map(({ c, n }) => (
              <SourceItem key={`${m.id}-${n}`} c={c} n={n} messageId={m.id} currentCaseId={currentCaseId} record={isCaseRecord(m)} />
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

/** An answer with labelled citations, each `[S#]` marker a button opening that one source (design assistant-polish,
 * decision 16); a marker without a matching citation stays plain text. */
function MarkedText({ m, onOpen }: { m: AssistantMessage; onOpen: (c: AssistantCitation) => void }) {
  const byLabel = new Map(m.citations.filter((c) => c.label).map((c) => [c.label as string, c]));
  return (
    <p className={s.text}>
      {markers(m.content ?? "").map((seg, i) => {
        const c = seg.label ? byLabel.get(seg.label) : undefined;
        return c ? (
          <button key={i} type="button" className={s.marker} aria-label={markerName(c)} onClick={() => onOpen(c)}>
            {seg.label}
          </button>
        ) : (
          <span key={i}>{seg.text}</span>
        );
      })}
    </p>
  );
}

function answerBody(m: AssistantMessage, onOpen: (c: AssistantCitation) => void) {
  if (m.content === null) return <p className={s.text}>{m.hidden_reason ?? A.hidden}</p>;
  if (m.outcome === "failed") {
    const family = m.error?.family ?? "error";
    return <p className={s.text}>{ASSISTANT_FAILURES[family] ?? m.error?.message ?? m.content}</p>;
  }
  if (hasLabels(m)) return <MarkedText m={m} onOpen={onOpen} />;
  return <p className={s.text}>{m.content}</p>;
}

/** Who answered, in words: a quick fact from the case record, the local model, SourceTrace or the preview. */
function answeredBy(m: AssistantMessage): string {
  if (isWorkAnswer(m)) return A.workAnswerBy;
  const key = isCaseRecord(m) ? "case_record" : (m.mode ?? "preview");
  return A.answerBy[key] ?? A.answerBy.preview!;
}

/** A My Work row's case: a link to the case page, or to the Case Claim modal for a waiting recommendation; words for a
 * case the reader can no longer open (design assistant-ollama-work, decision 9). */
function WorkCase({ c }: { c: AssistantCitation }) {
  if (!c.available) return <span className={s.muted}>{A.hiddenRow}</span>;
  const name = c.case.case_no_text ?? c.case.cnr ?? null;
  if (!name) return <span className={s.muted}>{A.noCase}</span>;
  if (!c.open) return <span className="cno">{name}</span>;
  return (
    <Link className="cno" href={c.open.href}>
      {name}
    </Link>
  );
}

/** A My Work answer (decision 4): the badge, how the list was chosen, the server's text (the count first), the rows,
 * "as of" and "Open the Full List". No markers, no Sources and no Copy to Note: the rows are the answer. */
function WorkAnswerCard({ m, n }: { m: AssistantMessage; n: number }) {
  const w = m.work!;
  const rows = m.citations.filter((c) => c.source_kind === "work_row");
  const asOf = rows.find((c) => c.work?.as_of)?.work?.as_of ?? m.created_at;
  const failed = m.outcome === "failed";
  const columns: Column<AssistantCitation>[] = [
    { key: "case", header: A.workCase, primary: true, rowHeader: true, cell: (c) => <WorkCase c={c} /> },
    ...workColumns(w.question).map(
      (field): Column<AssistantCitation> => ({
        key: field,
        header: labelFor(A.workFields, field),
        cell: (c) => {
          if (!c.available) return null;
          const value = c.work?.fields?.[field];
          if (field === "department") return typeof value === "string" && value ? <OfficeName code={value} /> : null;
          return workValue(field, value);
        },
      }),
    ),
  ];
  return (
    <div className={s.answer} aria-label={`${answeredBy(m)} ${n}`} role="group">
      <div className={s.answerHead}>
        <Badge tone="info">{A.fromYourLists}</Badge>
        <span>{A.outcomes[m.outcome ?? "answered"] ?? m.outcome}</span>
        <span>· {formatDateTime(m.created_at)}</span>
      </div>
      <p className={s.hint}>{labelFor(A.chosenBy, w.chosen_by)}</p>
      {/* the server writes every My Work text, a failure's included ("Your lists took too long to read; try again.") */}
      <p className={s.text}>{m.content}</p>
      {rows.length > 0 ? (
        <div className={s.inlineSources}>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(c) => `${m.id}-${c.label ?? ""}`}
            caption={w.list_label ? serverLabel(w.list_label) : A.workRows}
          />
          <p className={s.hint}>{A.asOf(formatDateTime(asOf))}</p>
        </div>
      ) : null}
      {w.full_list_href && !failed && w.total > 0 ? (
        <div className={s.foot}>
          <Link className={buttonClass("secondary")} href={w.full_list_href}>
            {A.openFullList}
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function AnswerCard({
  m,
  n,
  onCopy,
  onInclude,
  onOpen,
  onList,
  currentCaseId,
  onAskWork = null,
}: {
  m: AssistantMessage;
  n: number;
  onCopy: (() => void) | null;
  /** the suggestion's button (decision 4): only offered, never pressed for the reader */
  onInclude: (() => void) | null;
  /** a marker pressed: open that source's dialog (design assistant-polish, decision 16) */
  onOpen: (c: AssistantCitation) => void;
  /** "Sources (n)" pressed: open the full list */
  onList: () => void;
  currentCaseId?: string | null;
  /** design assistant-ollama-work, decision 11: "Ask in My Work", only offered, never pressed for the reader */
  onAskWork?: (() => void) | null;
}) {
  if (isWorkAnswer(m)) return <WorkAnswerCard m={m} n={n} />;
  const sources = m.citations.length;
  const record = isCaseRecord(m);
  const local = m.mode === "ollama" && !record;
  const labelled = hasLabels(m);
  const shown = m.content !== null && m.outcome !== "failed";
  return (
    <div className={s.answer} aria-label={`${answeredBy(m)} ${n}`} role="group">
      <div className={s.answerHead}>
        {m.mode === "preview" && !record ? <Badge>{A.previewBadge}</Badge> : null}
        {record ? <Badge tone="info">{A.caseRecordBadge}</Badge> : null}
        {local ? <Badge tone="info">{A.localModel}</Badge> : null}
        {local && m.engine?.model ? <span className="cno">{m.engine.model}</span> : null}
        <span>{A.outcomes[m.outcome ?? "answered"] ?? m.outcome}</span>
        <span>· {formatDateTime(m.created_at)}</span>
        {local && m.checks?.cut_short ? <Badge tone="warning">{A.cutShort}</Badge> : null}
      </div>
      {answerBody(m, onOpen)}
      {record && shown ? <p className={s.hint}>{A.caseRecordLine}</p> : null}
      {local && shown ? <p className={s.hint}>{A.localLine}</p> : null}
      {local && m.internal_used && m.content !== null ? <p className={s.hint}>{A.usesInternal}</p> : null}
      {local && (m.checks?.invalid_markers ?? 0) > 0 ? <p className={s.hint}>{A.removedReference}</p> : null}
      {onInclude && m.suggest_internal ? (
        <div className={s.suggest}>
          <span>{A.suggestInternal}</span>
          <Button variant="secondary" size="sm" onClick={onInclude}>
            {A.includeInternal}
          </Button>
        </div>
      ) : null}
      {onAskWork && m.suggest_work ? (
        <div className={s.suggest}>
          <span>{A.suggestWork}</span>
          <Button variant="secondary" size="sm" onClick={onAskWork}>
            {A.askInMyWork}
          </Button>
        </div>
      ) : null}
      {/* answers without markers keep their sources under the answer: their text has nothing to click */}
      {sources > 0 && !labelled ? (
        <div className={s.inlineSources}>
          <SourceList m={m} currentCaseId={currentCaseId} />
        </div>
      ) : null}
      {onCopy || (labelled && sources > 0) ? (
        <div className={s.foot}>
          {/* the normal size: on a phone an sm button outside a row is too small to press (size rule) */}
          {labelled && sources > 0 ? (
            <Button variant="secondary" onClick={onList}>
              {A.sourcesButton(sources)}
            </Button>
          ) : null}
          {onCopy ? (
            <Button variant="secondary" onClick={onCopy}>
              {A.copyToNote}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Thread({
  messages,
  pending,
  loading,
  onCopy,
  onInclude,
  onOpen,
  onList,
  includedAt,
  asking,
  currentCaseId,
  scrollRef,
  onAskWork = null,
}: {
  messages: AssistantMessage[];
  pending: string | null;
  loading: boolean;
  onCopy: ((m: AssistantMessage) => void) | null;
  onInclude: (() => void) | null;
  onOpen: (m: AssistantMessage, c: AssistantCitation) => void;
  onList: (m: AssistantMessage) => void;
  /** when this conversation's internal records were switched on (decision 4) */
  includedAt: string | null;
  asking: string;
  currentCaseId?: string | null;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  onAskWork?: ((m: AssistantMessage) => void) | null;
}) {
  const answers = messages.filter((m) => m.role === "assistant");
  const answered = new Set(answers.map((m) => m.reply_to_id));
  // the mark sits before the first question asked after the switch (earlier answers stay court-only)
  const firstAfter = includedAt ? messages.find((m) => m.role === "user" && switchedBefore(includedAt, m.created_at)) : undefined;
  const markAtEnd = !!includedAt && !firstAfter;
  const mark = <p className={s.includedHere}>{A.includedHere}</p>;
  // the box stays mounted while a conversation loads, so its height and focus do not jump
  return (
    <div ref={scrollRef} className={s.thread} tabIndex={0} role="log" aria-label={A.conversation} aria-live="polite">
      {loading ? <Loading lines={2} /> : null}
      {messages.length === 0 && !pending && !loading ? (
        <div className={s.empty}>
          <b>{A.emptyTitle}</b>
          <span>{A.emptyText}</span>
        </div>
      ) : null}
      {messages.map((m) =>
        m.role === "user" ? (
          <div key={m.id}>
            {firstAfter?.id === m.id ? mark : null}
            <div className={s.msg}>
              <div className={s.who}>{A.you}</div>
              <div className={s.bubble}>
                <div className={s.question}>{m.content}</div>
                {/* a question whose answer was never recorded (the process stopped between the two steps) */}
                {!answered.has(m.id) ? <p className={s.hint}>{A.noAnswer}</p> : null}
              </div>
            </div>
          </div>
        ) : (
          <div key={m.id} className={s.msg}>
            <div className={s.who}>{answeredBy(m)}</div>
            <div className={s.bubble}>
              <AnswerCard
                m={m}
                n={answers.indexOf(m) + 1}
                onCopy={onCopy && !isWorkAnswer(m) && m.outcome === "answered" && m.content !== null ? () => onCopy(m) : null}
                onInclude={onInclude}
                onOpen={(c) => onOpen(m, c)}
                onList={() => onList(m)}
                currentCaseId={currentCaseId}
                onAskWork={onAskWork ? () => onAskWork(m) : null}
              />
            </div>
          </div>
        ),
      )}
      {markAtEnd && messages.length > 0 ? mark : null}
      {pending !== null ? (
        <>
          <div className={s.msg}>
            <div className={s.who}>{A.you}</div>
            <div className={s.bubble}>
              <div className={s.question}>{pending}</div>
            </div>
          </div>
          <div className={s.msg} role="status">
            <div className={s.who} />
            <div className={cx(s.bubble, s.muted)}>{asking}</div>
          </div>
        </>
      ) : null}
    </div>
  );
}

/** One source in a dialog, opened from its marker (design assistant-polish, decision 16): its kind with the Internal
 * badge, its title, the excerpt of a court kind, "Text Given to the Model", and Close with the open link. The kit's
 * dialog traps the focus, closes on Escape and gives the focus back to the marker. Only what the API returned. */
function SourceDialog({
  open,
  m,
  c,
  onClose,
  currentCaseId,
}: {
  open: boolean;
  m: AssistantMessage | null;
  c: AssistantCitation | null;
  onClose: () => void;
  currentCaseId?: string | null;
}) {
  if (!m || !c) return null;
  const link = sourceLink(c, m.id);
  const subtitle = c.available
    ? c.source_kind === "case_details"
      ? (c.case.case_no_text ?? c.case.cnr ?? undefined)
      : (otherCaseName(c, currentCaseId) ?? undefined)
    : undefined;
  const court = c.source_kind === "court_order" || c.source_kind === "court_filing";
  return (
    <Dialog
      open={open}
      title={A.sourceTitle(c.label ?? "")}
      subtitle={subtitle}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {A.close}
          </Button>
          {link ? (
            link.newTab ? (
              <a className={buttonClass("primary")} href={link.href} target="_blank" rel="noopener noreferrer">
                {openWords(c, link)}
              </a>
            ) : (
              <Link className={buttonClass("primary")} href={link.href}>
                {openWords(c, link)}
              </Link>
            )
          ) : null}
        </>
      }
    >
      {c.available ? (
        <div className={s.sourceDialog}>
          <span className={s.kindLine}>
            {kindLabel(c)}
            {isInternal(c) ? <Badge tone="warning">{A.internalBadge}</Badge> : null}
          </span>
          <p className={s.sourceTitle}>{sourceWords(c)}</p>
          {court ? <Passage text={c.passage} /> : null}
          <TextGiven c={c} record={isCaseRecord(m)} />
        </div>
      ) : (
        <p>{A.sourceGoneNotice}</p>
      )}
    </Dialog>
  );
}

/** "Sources (n)": every source of one answer in a dialog, grouped Court Record and Internal Records with the uncited
 * ones collapsed, each with its open link (design assistant-polish, decision 16). */
function SourcesDialog({
  open,
  m,
  onClose,
  currentCaseId,
}: {
  open: boolean;
  m: AssistantMessage | null;
  onClose: () => void;
  currentCaseId?: string | null;
}) {
  if (!m) return null;
  return (
    <Dialog
      open={open}
      title={A.sourcesTitle}
      onClose={onClose}
      footer={
        <Button variant="secondary" onClick={onClose}>
          {A.close}
        </Button>
      }
    >
      <SourceList m={m} currentCaseId={currentCaseId} />
    </Dialog>
  );
}

function Composer({
  value,
  onChange,
  onSubmit,
  busy,
  status,
  primary,
  scope,
  extra,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  status: AssistantStatus | undefined;
  primary: boolean;
  scope: AssistantScope;
  /** beside the scope note: the case tab's "Include This Case's Internal Records" (decision 14) */
  extra?: React.ReactNode;
}) {
  const local = status?.mode === "ollama";
  const max = status?.limits.question_max_chars ?? 2000;
  const left = questionsLeft(status);
  const canSend = !busy && value.trim().length >= 3 && value.length <= max;
  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit();
  }
  return (
    <form className={s.composer} onSubmit={submit} aria-label={A.composer}>
      <TextArea
        label={A.question}
        placeholder={A.questionPlaceholder}
        hint={A.enterHint}
        value={value}
        rows={3}
        enterKeyHint="send"
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          // design assistant-polish, decision 1: Enter sends, Shift+Enter is a new line, Ctrl or Cmd+Enter still
          // sends; never while an input method is composing (keyCode 229 is older Safari's sign of it)
          if (e.key !== "Enter") return;
          if (e.nativeEvent.isComposing || e.keyCode === 229) return;
          if (e.shiftKey && !e.ctrlKey && !e.metaKey) return;
          e.preventDefault();
          if (canSend) onSubmit();
        }}
      />
      <div className={s.composerRow}>
        <span className={s.hint}>
          <CharCounter value={value} max={max} />
          {left !== null && status ? <> · {A.left(left, status.limits.questions_per_hour)}</> : null}
        </span>
        <Button type="submit" variant={primary ? "primary" : "secondary"} busy={busy} disabled={!canSend}>
          {A.ask}
        </Button>
      </div>
      {scope === "my_work" ? (
        <p className={s.hint}>{A.myWorkNote}</p>
      ) : local ? (
        <div className={s.scopeNote}>
          <p className={s.hint}>{A.ollamaScopeHint[scope]}</p>
          {extra}
        </div>
      ) : (
        <p className={s.hint}>
          {A.scopeHint[scope]} {A.neverSent}
        </p>
      )}
    </form>
  );
}

/** One scope's conversation: the latest by default, or the one chosen; `null` a new conversation. */
type Picked = Partial<Record<AssistantScope, string | null>>;

/**
 * The shared workspace of the case tab (`screen="case"`) and the page (`screen="page"`): one question at a time, the
 * three-step answer on the server, the thread read back from the API after each answer.
 */
function Workspace({
  screen,
  caseRef,
  caseId = null,
  noteMode = null,
  tab = null,
}: {
  screen: "case" | "page";
  caseRef?: string;
  caseId?: string | null;
  noteMode?: NoteMode | null;
  /** the page's `?tab=` (design assistant-ollama-work, decision 2) */
  tab?: string | null;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const status = useAssistantStatus();
  const me = useMe();
  // design assistant-ollama-work, decisions 1 and 2: the case tab is This Case only; the page's tabs come from the
  // server's scopes, the one in the address when offered, else My Work, else My Cases
  const scopes: AssistantScope[] = screen === "case" ? ["case"] : pageScopes(status.data);
  // a tab pressed (or "Ask in My Work") holds until the address's tab changes; then the address decides
  const [chosen, setChosen] = useState<{ from: string | null; scope: AssistantScope } | null>(null);
  const held = chosen && chosen.from === tab && scopes.includes(chosen.scope) ? chosen.scope : null;
  const scope: AssistantScope = screen === "case" ? "case" : (held ?? scopeForTab(tab, scopes) ?? "my_cases");
  const ready = screen === "case" || !!status.data;
  const [moreExamples, setMoreExamples] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [includeBusy, setIncludeBusy] = useState(false);
  const [includeError, setIncludeError] = useState<unknown>(null);
  const [picked, setPicked] = useState<Picked>({});
  // design assistant-polish, decision 16: the source opened from its marker, and the answer whose list is open
  // (the last one stays mounted while its dialog eases out)
  const [source, setSource] = useState<{ m: AssistantMessage; c: AssistantCitation } | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [listOf, setListOf] = useState<AssistantMessage | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [copying, setCopying] = useState<string | null>(null);
  const toast = useToast();
  const [view, setView] = useState<"list" | "thread">("thread");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const toEnd = useRef(true);
  const scopeCase = scope === "case" ? (caseRef ?? null) : null;

  const list = useQuery({
    queryKey: listKey(screen, scope, scopeCase),
    queryFn: () => fetchList(screen, scope, scopeCase),
    enabled: ready,
  });
  const latest = list.data?.items[0]?.id ?? null;
  const current = picked[scope] !== undefined ? (picked[scope] ?? null) : latest;
  const thread = useQuery({
    queryKey: threadKey(current ?? ""),
    queryFn: () => api<AssistantThread>(`/assistant/conversations/${encodeURIComponent(current!)}`, { query: { limit: 200 } }),
    enabled: !!current,
  });
  const messages = current ? (thread.data?.messages ?? []) : [];
  const answers = messages.filter((m) => m.role === "assistant");

  // a new answer scrolls the box to the newest message; choosing an older answer keeps the position
  useIsoLayoutEffect(() => {
    const el = scrollRef.current;
    if (el && toEnd.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages.length, pending, current]);

  async function ask(text: string, inScope: AssistantScope = scope, conversation: string | null = current) {
    const q = text.trim();
    if (q.length < 3 || pending !== null) return;
    setError(null);
    setPending(q);
    toEnd.current = true;
    try {
      const out = await api<AssistantAsk>("/assistant/ask", {
        method: "POST",
        body: {
          question: q,
          scope: inScope,
          case: inScope === "case" ? caseRef : undefined,
          conversation_id: conversation ?? undefined,
          include_related: true,
        },
      });
      const id = out.conversation.id;
      queryClient.setQueryData<AssistantThread>(threadKey(id), (old) => ({
        conversation: out.conversation,
        messages: [...(old?.messages ?? []), out.question, out.answer],
        has_more: old?.has_more ?? false,
      }));
      setPicked((p) => ({ ...p, [inScope]: id }));
      setQuestion("");
      setView("thread");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["assistant", "conversations"] }),
        queryClient.invalidateQueries({ queryKey: STATUS_KEY }),
      ]);
    } catch (err) {
      setError(err);
      setQuestion((v) => v || q);
    } finally {
      setPending(null);
    }
  }

  function newConversation() {
    setPicked((p) => ({ ...p, [scope]: null }));
    setError(null);
    setView("thread");
  }

  function openConversation(id: string) {
    setPicked((p) => ({ ...p, [scope]: id }));
    setView("thread");
    toEnd.current = true;
  }


  // design assistant-ollama, decision 4: the switch is the server's state of this case-tab conversation
  const local = status.data?.mode === "ollama";
  const includedAt = current && scope === "case" ? (thread.data?.conversation.internal_included_at ?? null) : null;
  const mayInclude =
    screen === "case" &&
    scope === "case" &&
    local &&
    status.data?.internal_records === "switch" &&
    canAny(me.data, CASE_READERS) &&
    !!caseRef;
  const offerInclude = mayInclude && !includedAt;

  async function include() {
    if (!caseRef) return;
    setIncludeBusy(true);
    setIncludeError(null);
    try {
      const out = await api<AssistantInternal>("/assistant/internal-records", {
        method: "POST",
        body: { case: caseRef, conversation_id: current ?? undefined },
      });
      setPicked((p) => ({ ...p, case: out.conversation_id }));
      setConfirming(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: threadKey(out.conversation_id) }),
        queryClient.invalidateQueries({ queryKey: ["assistant", "conversations"] }),
      ]);
    } catch (err) {
      setIncludeError(err);
    } finally {
      setIncludeBusy(false);
    }
  }

  const canCopy = screen === "case" && scope === "case" && !!noteMode;
  const copyMessage = copying ? (answers.find((m) => m.id === copying) ?? null) : null;
  const currentCaseId = screen === "case" ? caseId : null;
  const includeButton = offerInclude ? (
    <Button variant="secondary" size="sm" onClick={() => setConfirming(true)} disabled={pending !== null}>
      {A.includeInternal}
    </Button>
  ) : null;

  // design assistant-ollama-work, decision 2: a tab opens its own conversations; nothing is asked again
  function selectTab(href: string) {
    const key = new URLSearchParams(href.split("?")[1] ?? "").get("tab");
    const next = PAGE_TABS.find((t) => t.key === key)?.scope;
    if (next) setChosen({ from: tab, scope: next });
    setError(null);
    setView("thread");
    toEnd.current = true;
    router.replace(href);
  }

  const tabs =
    screen === "page" && scopes.length > 0 ? (
      <Tabs
        label={A.pageTabs}
        items={scopes.map((v) => ({ href: tabHref(v), label: labelFor(A.scopes, v), active: v === scope }))}
        onSelect={selectTab}
      />
    ) : null;

  // design assistant-ollama-work, decision 11: the same question asked in My Work, in a new conversation, on the click
  const askInWork =
    screen === "page" && scopes.includes("my_work") && scope !== "my_work"
      ? (m: AssistantMessage) => {
          const q = questionOf(messages, m)?.content;
          if (!q) return;
          setChosen({ from: tab, scope: "my_work" });
          router.replace(tabHref("my_work"));
          void ask(q, "my_work", null);
        }
      : null;

  const workExamples = scope === "my_work" ? (status.data?.work_questions ?? []).map((q) => q.example) : [];
  const examples = scope === "my_work" ? workExamples : (A.suggested[scope] ?? []);
  const shownExamples = scope === "my_work" && !moreExamples ? examples.slice(0, 6) : examples;

  const threadColumn = (
    <div className={cx(s.column, s.threadColumn)}>
      <div className={s.head}>
        {screen === "page" ? (
          <Button variant="ghost" className={s.back} onClick={() => setView("list")}>
            {A.backToList}
          </Button>
        ) : null}
        <h2 className="h3">{thread.data?.conversation.title ?? A.conversation}</h2>
        <Button variant="secondary" onClick={newConversation} disabled={pending !== null}>
          {A.newConversation}
        </Button>
      </div>
      {includedAt ? (
        <div className={s.included} role="status">
          <div>
            <b>{A.includedBanner}</b> <span className={s.hint}>{A.includedSince(formatDateTime(includedAt))}</span>
            <p className={s.hint}>{A.includedLine}</p>
          </div>
          {/* the normal size: on a phone it stands alone under the banner's text, outside any row (size rule) */}
          <Button variant="secondary" onClick={newConversation} disabled={pending !== null}>
            {A.courtOnlyConversation}
          </Button>
        </div>
      ) : null}
      <Thread
        messages={messages}
        pending={pending}
        loading={!ready || list.isPending || (!!current && thread.isPending)}
        onOpen={(m, c) => {
          setSource({ m, c });
          setSourceOpen(true);
        }}
        onList={(m) => {
          setListOf(m);
          setListOpen(true);
        }}
        onCopy={canCopy ? (m) => setCopying(m.id) : null}
        onInclude={offerInclude ? () => setConfirming(true) : null}
        includedAt={includedAt}
        asking={scope === "my_work" ? A.askingWork : local ? A.askingOllama : A.asking}
        currentCaseId={currentCaseId}
        scrollRef={scrollRef}
        onAskWork={askInWork}
      />
      <ErrorBanner error={list.error ?? thread.error} onRetry={() => (list.error ? list.refetch() : thread.refetch())} />
      {messages.length === 0 && pending === null && ready && !list.isPending && !(current && thread.isPending) && examples.length > 0 ? (
        <div className={s.examples}>
          <ChipGroup label={A.suggestions}>
            {shownExamples.map((q) => (
              <Chip key={q} onClick={() => setQuestion(q)}>
                {q}
              </Chip>
            ))}
          </ChipGroup>
          {scope === "my_work" && examples.length > 6 ? (
            <Button variant="ghost" size="sm" onClick={() => setMoreExamples((v) => !v)} aria-expanded={moreExamples}>
              {moreExamples ? A.fewerExamples : A.moreExamples(examples.length - 6)}
            </Button>
          ) : null}
        </div>
      ) : null}
      <ErrorBanner error={error} messages={ASSISTANT_ERRORS} />
      {!confirming ? <ErrorBanner error={includeError} messages={ASSISTANT_ERRORS} /> : null}
      <Composer
        value={question}
        onChange={setQuestion}
        onSubmit={() => void ask(question)}
        busy={pending !== null}
        status={status.data}
        primary={screen === "page"}
        scope={scope}
        extra={includeButton}
      />
      {screen === "case" ? (
        <p className={s.hint}>
          {A.openAssistantLine} <Link href="/assistant">{A.openAssistant}</Link>
        </p>
      ) : null}
    </div>
  );

  // the page's tabs come only from the status (decision 2): a failed status read shows the error with Try Again, never
  // the loading lines for ever; the case tab needs no status to list its conversation and goes on without it
  if (screen === "page" && !status.data && status.isError) {
    return (
      <div className={s.workspace}>
        <PageHeader title={A.title} subtitle={A.subtitle} />
        <ErrorBanner error={status.error} onRetry={() => void status.refetch()} retrySize="md" />
      </div>
    );
  }

  return (
    <div className={s.workspace}>
      {screen === "page" ? <PageHeader title={A.title} subtitle={A.subtitle} /> : null}
      {tabs}
      <AssistantBanner status={status.data} />
      <ReadinessNotice status={status.data} />
      {screen === "page" ? (
        <div className={s.pageGrid} data-view={view}>
          <aside className={cx(s.column, s.listColumn)} aria-label={A.conversations}>
            <Card title={A.conversations}>
              {!ready || list.isPending ? (
                <Loading lines={2} />
              ) : (list.data?.items.length ?? 0) === 0 ? (
                <EmptyState compact title={A.noConversationsTitle}>
                  {A.noConversations}
                </EmptyState>
              ) : (
                <ul className={s.conversations}>
                  {list.data!.items.map((c) => (
                    <li key={c.id}>
                      <button
                        type="button"
                        className={s.conv}
                        aria-current={c.id === current ? "true" : undefined}
                        aria-label={A.openConversation(c.title ?? A.conversation)}
                        onClick={() => openConversation(c.id)}
                      >
                        {c.title ?? A.conversation}
                        {c.internal_included_at ? <Badge tone="warning">{A.includedMark}</Badge> : null}
                        <small>{formatDateTime(c.last_message_at ?? c.created_at)}</small>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <p className={s.lockline}>{A.private}</p>
            </Card>
          </aside>
          {threadColumn}
        </div>
      ) : (
        <div className={s.caseGrid}>{threadColumn}</div>
      )}
      <SourceDialog
        open={sourceOpen}
        m={source?.m ?? null}
        c={source?.c ?? null}
        onClose={() => setSourceOpen(false)}
        currentCaseId={currentCaseId}
      />
      <SourcesDialog open={listOpen} m={listOf} onClose={() => setListOpen(false)} currentCaseId={currentCaseId} />
      {canCopy && caseRef && noteMode ? (
        <NoteDialog
          open={!!copyMessage}
          caseRef={caseRef}
          mode={noteMode}
          initialBody={copyMessage ? noteText(copyMessage) : undefined}
          initialVisibility={copyMessage ? (narrowestVisibility(copyMessage) ?? undefined) : undefined}
          warning={copyMessage?.internal_used ? A.copyInternalWarning : undefined}
          onClose={() => setCopying(null)}
          onDone={(text) => toast(text)}
        />
      ) : null}
      {mayInclude ? (
        <ConfirmDialog
          open={confirming}
          title={A.includeTitle}
          onClose={() => {
            setConfirming(false);
            setIncludeError(null);
          }}
          onConfirm={() => void include()}
          busy={includeBusy}
          error={includeError}
          messages={ASSISTANT_ERRORS}
          confirmLabel={A.include}
          cancelLabel={A.cancel}
        >
          <p>{A.includeText}</p>
        </ConfirmDialog>
      ) : null}
    </div>
  );
}

/** The case page's Assistant tab (`/cases/[ref]/assistant`). */
export function CaseAssistant({ caseRef }: { caseRef: string }) {
  const me = useMe();
  const detail = useCase(caseRef);
  if (me.isPending) return <Loading />;
  if (!showsAssistant(me.data)) return <EmptyState>{A.off}</EmptyState>;
  return (
    <section aria-label={A.tabTitle}>
      <Workspace
        screen="case"
        caseRef={caseRef}
        caseId={detail.data?.id ?? null}
        noteMode={detail.data?.workflow?.note_mode ?? null}
      />
    </section>
  );
}

/** The Assistant page of the menu (`/assistant?tab=`): My Work, My Cases and All Court Orders (design
 * assistant-ollama-work, decision 2), the conversation list on the left. */
export function AssistantPage({ tab = null }: { tab?: string | null } = {}) {
  const me = useMe();
  if (me.isPending) return <Loading />;
  if (!showsAssistant(me.data)) {
    return (
      <div className="stack">
        <PageHeader title={A.title} />
        <EmptyState>{A.off}</EmptyState>
      </div>
    );
  }
  return <Workspace screen="page" tab={tab} />;
}
