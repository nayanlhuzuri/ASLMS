"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, apiUrl } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { VISIBILITY } from "@/lib/labels";
import type { AssistantMessage, AssistantStatus, Citation, Conversation } from "@/lib/types";
import { Button } from "../../ui/Button";
import { Select } from "../../ui/Field";
import { Icon } from "../../ui/Icon";
import { Card, CardHead, Notice } from "../../ui/Layout";
import { Async, Empty, ErrorState } from "../../ui/States";
import { useToast } from "../../ui/Toast";
import s from "./detail.module.css";

function citationsOf(m: AssistantMessage): Citation[] {
  return (m.citations ?? []).map((c) => {
    const o = c as Record<string, unknown>;
    return {
      title: typeof o.title === "string" ? o.title : undefined,
      reference: typeof o.reference === "string" ? o.reference : undefined,
      document_id: typeof o.document_id === "string" ? o.document_id : undefined,
      url: typeof o.url === "string" ? o.url : undefined,
    };
  });
}

function CitationLink({ c, n }: { c: Citation; n: number }) {
  const label = c.title || c.reference || "Source";
  const inner = (
    <>
      <span className="mono" style={{ fontWeight: 500 }}>
        [{n}]
      </span>
      {label}
    </>
  );
  if (c.document_id) {
    return (
      <a className={s.cite} href={apiUrl(`/documents/${c.document_id}/download`)} target="_blank" rel="noopener">
        {inner}
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
    );
  }
  return <span className={s.cite}>{inner}</span>;
}

function BotMessage({ m, caseMode, onCopy, copying }: { m: AssistantMessage; caseMode: boolean; onCopy: (m: AssistantMessage, visibility: string) => void; copying: boolean }) {
  const cites = citationsOf(m);
  const [vis, setVis] = useState("case_scope");
  return (
    <div className={s.bubbleBot}>
      <div className={s.botHead}>
        <Icon name="chat" size={14} />
        Case Assistant · SourceTrace · {fmtDateTime(m.created_at)}
      </div>
      <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
      {cites.length ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {cites.map((c, i) => (
            <CitationLink key={i} c={c} n={i + 1} />
          ))}
        </div>
      ) : null}
      {caseMode ? (
        <div className={s.botActions}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <span className="muted">Note visible to</span>
            <Select value={vis} onChange={(e) => setVis(e.target.value)} style={{ width: "auto", minHeight: 36 }}>
              {VISIBILITY.map((v) => (
                <option key={v.value} value={v.value}>
                  {v.short}
                </option>
              ))}
            </Select>
          </label>
          <Button small icon="file" busy={copying} onClick={() => onCopy(m, vis)}>
            Copy to case note
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The Case Assistant chat (per case) or general research. Questions are saved even while SourceTrace is not
 * connected; the backend then answers that the assistant is unavailable.
 */
export function AssistantChat({ caseId }: { caseId?: string }) {
  const toast = useToast();
  const caseMode = !!caseId;
  const status = useApi<AssistantStatus>("/assistant/status");
  const list = useApi<Conversation[]>(caseMode ? `/cases/${caseId}/assistant` : "/research");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [active, setActive] = useState<Conversation | null>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [copying, setCopying] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  // Pick the most recent conversation once the list arrives.
  useEffect(() => {
    if (activeId === null && list.data && list.data.length) setActiveId(list.data[0].id);
  }, [list.data, activeId]);

  // Load the selected conversation with its messages (the research list may omit them).
  useEffect(() => {
    if (!activeId) {
      setActive(null);
      return;
    }
    const fromList = list.data?.find((c) => c.id === activeId);
    if (fromList && fromList.messages && fromList.messages.length) {
      setActive(fromList);
      return;
    }
    let alive = true;
    setLoadError(null);
    api
      .get<Conversation>(`/assistant/conversations/${activeId}`)
      .then((c) => {
        if (alive) setActive(c);
      })
      .catch((e: unknown) => {
        if (alive) setLoadError(e instanceof Error ? e.message : "Could not load the conversation.");
      });
    return () => {
      alive = false;
    };
  }, [activeId, list.data]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [active?.messages?.length]);

  const ask = async (e?: FormEvent) => {
    e?.preventDefault();
    const q = question.trim();
    if (!q) return;
    setBusy(true);
    try {
      const conv = await api.post<Conversation>(caseMode ? `/cases/${caseId}/assistant` : "/research", {
        question: q,
        conversation_id: activeId,
      });
      setQuestion("");
      setActive(conv);
      setActiveId(conv.id);
      list.reload();
    } catch (err) {
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void ask();
  };

  const copy = async (m: AssistantMessage, visibility: string) => {
    setCopying(m.id);
    try {
      await api.post(`/assistant/messages/${m.id}/to-note`, { visibility });
      toast.success("Answer copied into the notes trail, with its references.");
    } catch (err) {
      toast.error(err);
    } finally {
      setCopying(null);
    }
  };

  const connected = status.data?.connected ?? true;
  const messages = active?.messages ?? [];
  const cites = messages.filter((m) => m.role !== "user").flatMap(citationsOf);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {status.data && !status.data.connected ? (
        <Notice tone="warning">
          <Icon name="info" size={16} />
          SourceTrace not connected (Phase 3). Questions are saved and answered with a notice until the research service is connected.
        </Notice>
      ) : null}
      <div className={s.assistant}>
        <Card className={s.convs} labelledBy="conv-h">
          <CardHead
            id="conv-h"
            title="Conversations"
            caption
            actions={
              <Button
                small
                onClick={() => {
                  setActiveId(null);
                  setActive(null);
                  document.getElementById("assistant-q")?.focus();
                }}
              >
                New
              </Button>
            }
          />
          <Async state={list} loadingLabel="Loading conversations">
            {(convs) =>
              convs.length === 0 ? (
                <Empty title="No conversations yet" />
              ) : (
                <ul className={s.convList}>
                  {convs.map((c) => (
                    <li key={c.id}>
                      <button type="button" className={`${s.convItem} ${c.id === activeId ? s.convActive : ""}`} aria-current={c.id === activeId ? "true" : undefined} onClick={() => setActiveId(c.id)}>
                        <strong style={{ fontWeight: 600 }}>{c.title || "Untitled conversation"}</strong>
                        <span className="muted">{fmtDateTime(c.last_message_at, "No messages")}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )
            }
          </Async>
          <p className="muted" style={{ fontSize: 12 }}>
            <Icon name="lock" size={12} /> Conversations are visible only to you.
          </p>
        </Card>
        <div className={s.chat}>
          <div className={s.messages} aria-live="polite">
            {loadError ? <ErrorState message={loadError} /> : null}
            {messages.length === 0 ? (
              <Empty title={caseMode ? "Ask about this case" : "Ask a research question"} center>
                {caseMode
                  ? "Answers draw on this case's orders and court filings, related past cases, and the Acts, rules and policies in SourceTrace."
                  : "Search past orders and the Acts, rules and policies in SourceTrace, without a particular case."}
              </Empty>
            ) : (
              messages.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className={s.bubbleUser}>
                    {m.content}
                  </div>
                ) : (
                  <BotMessage key={m.id} m={m} caseMode={caseMode} onCopy={copy} copying={copying === m.id} />
                ),
              )
            )}
            <div ref={bottom} />
          </div>
          <form className={s.composer} onSubmit={ask}>
            <label style={{ flexGrow: 1 }}>
              <span className="sr-only">{caseMode ? "Ask about this case" : "Research question"}</span>
              <textarea
                id="assistant-q"
                className="textarea"
                rows={2}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={onKey}
                placeholder={caseMode ? "Ask about this case, related past cases, or the Acts, rules and policies" : "Ask about past orders, Acts, rules or policies"}
                maxLength={2000}
              />
            </label>
            <Button type="submit" variant="primary" icon="send" busy={busy} disabled={!question.trim()} aria-label="Send question">
              Send
            </Button>
          </form>
          <span className="muted" style={{ fontSize: 12 }}>
            Ctrl+Enter sends. {connected ? "Check each reference before relying on an answer." : "Answers arrive once SourceTrace is connected."}
          </span>
        </div>
        <Card className={s.sources} labelledBy="src-h">
          <CardHead id="src-h" title="Sources used" caption />
          {cites.length ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
              {cites.map((c, i) => (
                <CitationLink key={i} c={c} n={i + 1} />
              ))}
            </div>
          ) : (
            <p className="muted" style={{ fontSize: 13 }}>
              References cited in answers appear here and open in the portal.
            </p>
          )}
          <Notice tone="warning">
            <Icon name="lock" size={16} />
            Internal documents and notes are never sent to SourceTrace.
          </Notice>
        </Card>
      </div>
    </div>
  );
}
