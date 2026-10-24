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
  EmptyState,
  ErrorBanner,
  Loading,
  Notice,
  PageHeader,
  SegmentedSwitch,
  TextArea,
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
  AssistantMessage,
  AssistantScope,
  AssistantStatus,
  AssistantThread,
} from "@/lib/api/types";
import { highlights, noteText, otherCaseName, questionsLeft, scopesFor, sourceLink, sourceWords } from "@/lib/assistant";
import { formatDateTime } from "@/lib/format";
import { ASSISTANT_ERRORS, ASSISTANT_FAILURES, T } from "@/lib/messages";
import { showsAssistant } from "@/lib/routes";

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
  if (status.state === "ready") return <Notice>{A.sourcetraceBanner}</Notice>;
  return null;
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
  if (!c.available) {
    // the API names nothing of a source the reader can no longer reach (no type, date, page or case)
    return (
      <li className={s.source}>
        <span className={s.num} aria-hidden="true">
          {n}
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
    <li className={s.source}>
      <span className={s.num} aria-hidden="true">
        {n}
      </span>
      <div className={s.sourceBody}>
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
      </div>
    </li>
  );
}

/** The sources of one answer, the related orders of other cases apart (decision 14). */
function SourceList({ m, currentCaseId }: { m: AssistantMessage; currentCaseId?: string | null }) {
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

function answerBody(m: AssistantMessage) {
  if (m.content === null) return <p className={s.text}>{m.hidden_reason ?? A.hidden}</p>;
  if (m.outcome === "failed") {
    const family = m.error?.family ?? "error";
    return <p className={s.text}>{ASSISTANT_FAILURES[family] ?? m.error?.message ?? m.content}</p>;
  }
  return <p className={s.text}>{m.content}</p>;
}

function AnswerCard({
  m,
  n,
  total,
  selected,
  onSelect,
  onCopy,
  currentCaseId,
}: {
  m: AssistantMessage;
  n: number;
  total: number;
  selected: boolean;
  onSelect: () => void;
  onCopy: (() => void) | null;
  currentCaseId?: string | null;
}) {
  const sources = m.citations.length;
  return (
    <div className={s.answer} data-selected={selected} aria-label={`${A.answerBy[m.mode ?? "preview"] ?? A.answerBy.preview} ${n}`} role="group">
      <div className={s.answerHead}>
        {m.mode === "preview" ? <Badge>{A.previewBadge}</Badge> : null}
        <span>{A.outcomes[m.outcome ?? "answered"] ?? m.outcome}</span>
        <span>· {formatDateTime(m.created_at)}</span>
        {total > 1 && sources > 0 && !selected ? (
          <button type="button" className={s.choose} onClick={onSelect}>
            {A.chooseAnswer(n)}
          </button>
        ) : null}
      </div>
      {answerBody(m)}
      {sources > 0 ? (
        <div className={s.inlineSources}>
          <SourceList m={m} currentCaseId={currentCaseId} />
        </div>
      ) : null}
      {onCopy ? (
        <div className={s.foot}>
          <Button variant="secondary" size="sm" onClick={onCopy}>
            {A.copyToNote}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function Thread({
  messages,
  pending,
  loading,
  selectedId,
  onSelect,
  onCopy,
  currentCaseId,
  scrollRef,
}: {
  messages: AssistantMessage[];
  pending: string | null;
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onCopy: ((m: AssistantMessage) => void) | null;
  currentCaseId?: string | null;
  scrollRef: React.RefObject<HTMLDivElement | null>;
}) {
  const answers = messages.filter((m) => m.role === "assistant");
  const answered = new Set(answers.map((m) => m.reply_to_id));
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
          <div key={m.id} className={s.msg}>
            <div className={s.who}>{A.you}</div>
            <div className={s.bubble}>
              <div className={s.question}>{m.content}</div>
              {/* a question whose answer was never recorded (the process stopped between the two steps) */}
              {!answered.has(m.id) ? <p className={s.hint}>{A.noAnswer}</p> : null}
            </div>
          </div>
        ) : (
          <div key={m.id} className={s.msg}>
            <div className={s.who}>{A.answerBy[m.mode ?? "preview"] ?? A.answerBy.preview}</div>
            <div className={s.bubble}>
              <AnswerCard
                m={m}
                n={answers.indexOf(m) + 1}
                total={answers.length}
                selected={m.id === selectedId}
                onSelect={() => onSelect(m.id)}
                onCopy={onCopy && m.outcome === "answered" && m.content !== null ? () => onCopy(m) : null}
                currentCaseId={currentCaseId}
              />
            </div>
          </div>
        ),
      )}
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
            <div className={cx(s.bubble, s.muted)}>{A.asking}</div>
          </div>
        </>
      ) : null}
    </div>
  );
}

function SidePanel({ m, n, total, currentCaseId }: { m: AssistantMessage | null; n: number; total: number; currentCaseId?: string | null }) {
  return (
    <aside className={s.sidePanel} aria-label={A.sources}>
      <Card title={m && total > 1 ? A.sourcesOf(n) : A.sources}>
        {m && m.citations.length ? <SourceList m={m} currentCaseId={currentCaseId} /> : <p className={s.hint}>{A.noSources}</p>}
      </Card>
    </aside>
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
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
  status: AssistantStatus | undefined;
  primary: boolean;
  scope: AssistantScope;
}) {
  const max = status?.limits.question_max_chars ?? 2000;
  const left = questionsLeft(status);
  function submit(e: FormEvent) {
    e.preventDefault();
    onSubmit();
  }
  return (
    <form className={s.composer} onSubmit={submit} aria-label={A.composer}>
      <TextArea
        label={A.question}
        placeholder={A.questionPlaceholder}
        value={value}
        rows={3}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            onSubmit();
          }
        }}
      />
      <div className={s.composerRow}>
        <span className={s.hint}>
          <CharCounter value={value} max={max} />
          {left !== null && status ? <> · {A.left(left, status.limits.questions_per_hour)}</> : null}
        </span>
        <Button type="submit" variant={primary ? "primary" : "secondary"} busy={busy} disabled={busy || value.trim().length < 3 || value.length > max}>
          {A.ask}
        </Button>
      </div>
      <p className={s.hint}>
        {A.scopeHint[scope]} {A.neverSent}
      </p>
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
  const scopes = scopesFor(screen);
  const [scope, setScope] = useState<AssistantScope>(scopes[0]!);
  const [picked, setPicked] = useState<Picked>({});
  const [selected, setSelected] = useState<string | null>(null);
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
  const selectedAnswer = answers.find((m) => m.id === selected) ?? answers[answers.length - 1] ?? null;
  const selectedN = selectedAnswer ? answers.indexOf(selectedAnswer) + 1 : 0;

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
      setSelected(out.answer.id);
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
    setSelected(null);
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
    setSelected(null);
    setError(null);
    setView("thread");
  }

  function openConversation(id: string) {
    setPicked((p) => ({ ...p, [scope]: id }));
    setSelected(null);
    setView("thread");
    toEnd.current = true;
  }


  const canCopy = screen === "case" && scope === "case" && !!noteMode;
  const copyMessage = copying ? (answers.find((m) => m.id === copying) ?? null) : null;
  const currentCaseId = screen === "case" ? caseId : null;

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
          <Button variant="ghost" size="sm" className={s.back} onClick={() => setView("list")}>
            {A.backToList}
          </Button>
        ) : null}
        <h2 className="h3">{thread.data?.conversation.title ?? A.conversation}</h2>
        <Button variant="secondary" size="sm" onClick={newConversation} disabled={pending !== null}>
          {A.newConversation}
        </Button>
      </div>
      <Thread
        messages={messages}
        pending={pending}
        loading={list.isPending || (!!current && thread.isPending)}
        selectedId={selectedAnswer?.id ?? null}
        onSelect={(id) => {
          toEnd.current = false;
          setSelected(id);
        }}
        onCopy={canCopy ? (m) => setCopying(m.id) : null}
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
      {notice ? <Notice>{notice}</Notice> : null}
      <Composer
        value={question}
        onChange={setQuestion}
        onSubmit={() => void ask(question)}
        busy={pending !== null}
        status={status.data}
        primary={screen === "page"}
        scope={scope}
      />
    </div>
  );

  const side = <SidePanel m={selectedAnswer} n={selectedN} total={answers.length} currentCaseId={currentCaseId} />;

  return (
    <div className={s.workspace}>
      {screen === "page" ? <PageHeader title={A.title} subtitle={A.subtitle} actions={switcher} /> : null}
      <AssistantBanner status={status.data} />
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
          {side}
        </div>
      ) : (
        <div className={s.caseGrid}>
          {threadColumn}
          {side}
        </div>
      )}
      {canCopy && caseRef && noteMode ? (
        <NoteDialog
          open={!!copyMessage}
          caseRef={caseRef}
          mode={noteMode}
          initialBody={copyMessage ? noteText(copyMessage) : undefined}
          onClose={() => setCopying(null)}
          onDone={(text) => setNotice(text)}
        />
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
