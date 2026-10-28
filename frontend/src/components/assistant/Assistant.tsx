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
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";

import {
  Badge,
  Button,
  Card,
  CharCounter,
  Chip,
  ChipGroup,
  ConfirmDialog,
  Dialog,
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  PageHeader,
  SegmentedSwitch,
  TextArea,
  buttonClass,
  cx,
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
  kindLabel,
  markerName,
  markers,
  narrowestVisibility,
  noteText,
  openWords,
  otherCaseName,
  questionsLeft,
  scopesFor,
  sourceId,
  sourceLink,
  sourceWords,
  switchedBefore,
} from "@/lib/assistant";
import { canAny } from "@/lib/can";
import { formatDateTime } from "@/lib/format";
import { ASSISTANT_ERRORS, ASSISTANT_FAILURES, T } from "@/lib/messages";
import { CASE_READERS, showsAssistant } from "@/lib/routes";

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

/** "Text Given to the Model" under a local-model source (decision 9: re-rendered by the server at read time). */
function TextGiven({ c }: { c: AssistantCitation }) {
  if (!c.label) return null;
  return (
    <details className={s.given}>
      <summary>{A.textGiven}</summary>
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
}: {
  c: AssistantCitation;
  n: number;
  messageId: string;
  currentCaseId?: string | null;
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
        <TextGiven c={c} />
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
        <SourceItem key={`${m.id}-${n}`} c={c} n={n} messageId={m.id} currentCaseId={currentCaseId} />
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
            <SourceItem key={`${m.id}-${n}`} c={c} n={n} messageId={m.id} currentCaseId={currentCaseId} />
          ))}
        </ul>
      ) : null}
      {related.length ? (
        <>
          <p className={s.group}>{A.related}</p>
          <ul className={s.sources} aria-label={A.related}>
            {related.map(({ c, n }) => (
              <SourceItem key={`${m.id}-${n}`} c={c} n={n} messageId={m.id} currentCaseId={currentCaseId} />
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
  const key = isCaseRecord(m) ? "case_record" : (m.mode ?? "preview");
  return A.answerBy[key] ?? A.answerBy.preview!;
}

function AnswerCard({
  m,
  n,
  onCopy,
  onInclude,
  onOpen,
  onList,
  currentCaseId,
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
}) {
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
                onCopy={onCopy && m.outcome === "answered" && m.content !== null ? () => onCopy(m) : null}
                onInclude={onInclude}
                onOpen={(c) => onOpen(m, c)}
                onList={() => onList(m)}
                currentCaseId={currentCaseId}
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
          <TextGiven c={c} />
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
      {local ? (
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
}: {
  screen: "case" | "page";
  caseRef?: string;
  caseId?: string | null;
  noteMode?: NoteMode | null;
}) {
  const queryClient = useQueryClient();
  const status = useAssistantStatus();
  const me = useMe();
  const scopes = scopesFor(screen);
  const [confirming, setConfirming] = useState(false);
  const [includeBusy, setIncludeBusy] = useState(false);
  const [includeError, setIncludeError] = useState<unknown>(null);
  const [scope, setScope] = useState<AssistantScope>(scopes[0]!);
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
  const [notice, setNotice] = useState<string | null>(null);
  const [view, setView] = useState<"list" | "thread">("thread");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const toEnd = useRef(true);
  const scopeCase = scope === "case" ? (caseRef ?? null) : null;

  const list = useQuery({
    queryKey: listKey(screen, scope, scopeCase),
    queryFn: () => fetchList(screen, scope, scopeCase),
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
    setNotice(null);
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

  // switching the scope searches the last question again, in that scope's open (or latest) conversation
  async function changeScope(next: string) {
    const last = [...messages].reverse().find((m) => m.role === "user");
    const nextScope = next as AssistantScope;
    setScope(nextScope);
    setError(null);
    toEnd.current = true;
    if (!last?.content) return;
    let conversation: string | null;
    if (picked[nextScope] !== undefined) {
      conversation = picked[nextScope] ?? null;
    } else {
      const nextCase = nextScope === "case" ? (caseRef ?? null) : null;
      try {
        const data = await queryClient.fetchQuery({
          queryKey: listKey(screen, nextScope, nextCase),
          queryFn: () => fetchList(screen, nextScope, nextCase),
        });
        conversation = data.items[0]?.id ?? null;
      } catch (err) {
        setError(err);
        return;
      }
    }
    await ask(last.content, nextScope, conversation);
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

  const switcher =
    scopes.length > 1 ? (
      <SegmentedSwitch
        label={A.searchIn}
        options={scopes.map((v) => ({ value: v, label: A.scopes[v] ?? v }))}
        value={scope}
        onChange={changeScope}
      />
    ) : null;

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
        loading={list.isPending || (!!current && thread.isPending)}
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
        asking={local ? A.askingOllama : A.asking}
        currentCaseId={currentCaseId}
        scrollRef={scrollRef}
      />
      <ErrorBanner error={list.error ?? thread.error} onRetry={() => (list.error ? list.refetch() : thread.refetch())} />
      {messages.length === 0 && pending === null && !list.isPending && !(current && thread.isPending) ? (
        <ChipGroup label={A.suggestions}>
          {(A.suggested[scope] ?? []).map((q) => (
            <Chip key={q} onClick={() => setQuestion(q)}>
              {q}
            </Chip>
          ))}
        </ChipGroup>
      ) : null}
      <ErrorBanner error={error} messages={ASSISTANT_ERRORS} />
      {!confirming ? <ErrorBanner error={includeError} messages={ASSISTANT_ERRORS} /> : null}
      {notice ? <Notice>{notice}</Notice> : null}
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
    </div>
  );

  return (
    <div className={s.workspace}>
      {screen === "page" ? <PageHeader title={A.title} subtitle={A.subtitle} actions={switcher} /> : null}
      <AssistantBanner status={status.data} />
      <ReadinessNotice status={status.data} />
      {screen === "case" ? switcher : null}
      {screen === "page" ? (
        <div className={s.pageGrid} data-view={view}>
          <aside className={cx(s.column, s.listColumn)} aria-label={A.conversations}>
            <Card title={A.conversations}>
              {list.isPending ? (
                <Loading lines={2} />
              ) : (list.data?.items.length ?? 0) === 0 ? (
                <p className={s.hint}>{A.noConversations}</p>
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
          onDone={(text) => setNotice(text)}
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

/** The Assistant page of the menu (`/assistant`): My cases | All court orders, the conversation list on the left. */
export function AssistantPage() {
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
  return <Workspace screen="page" />;
}
