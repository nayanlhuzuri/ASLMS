"use client";

/**
 * The cited passage on its page (design research-index-portal, decisions 12 to 15): the heading "The Cited Passage",
 * "Page n of m, as ASLMS stored the order's text", the page text in the kit's vertical `ScrollBox` (wrapped, never a
 * sideways scroll) with the passage shaded and the quoted words shaded more strongly and underlined (colour is never
 * the only sign), a legend naming only the parts present, the line for a quote not found exactly, and the box scrolled
 * to the first mark on opening (instantly under reduced motion, without moving the dialog or the page). A citation
 * whose order's text has changed shows only the "Text Has Changed" notice: no page text and no marks.
 *
 * `CitedPassage` reads `GET /assistant/messages/{id}/sources/{label}/passage` once per message and label (cached): a
 * 404 says the passage cannot be shown, a failure shows Try Again. Court-public text; nothing here is sent anywhere.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { Badge, Card, ErrorBanner, Loading, ScrollBox, usePrefersReducedMotion } from "@/components/ui";
import { api, ApiError } from "@/lib/api/client";
import type { AssistantPassage } from "@/lib/api/types";
import { T } from "@/lib/messages";
import { passageRuns, type Highlight } from "@/lib/research";

import s from "./assistant.module.css";

const P = T.assistant.passage;

export function passageKey(messageId: string, label: string) {
  return ["assistant", "passage", messageId, label] as const;
}

/** The "Text Has Changed" badge and its line (decision 15). */
export function TextChangedNote() {
  return (
    <div className={s.changed} data-ui="text-changed">
      <Badge tone="warning">{T.assistant.textChanged}</Badge>
      <p className={s.hint}>{T.assistant.textChangedLine}</p>
    </div>
  );
}

export function PassageView({
  passage,
  showHeading = true,
}: {
  passage: Pick<AssistantPassage, "page" | "page_count" | "page_text" | "highlights" | "text_changed">;
  /** off inside a card whose title already says "The Cited Passage" */
  showHeading?: boolean;
}) {
  const box = useRef<HTMLDivElement | null>(null);
  const reduced = usePrefersReducedMotion();
  const highlights = (passage.highlights ?? []) as Highlight[];
  const runs = passage.text_changed ? [] : passageRuns(passage.page_text ?? "", highlights);
  const hasPassage = runs.some((r) => r.passage);
  const hasQuote = runs.some((r) => r.quote);
  const inexact = highlights.some((h) => h.kind === "quote" && !h.exact) || (!hasQuote && highlights.some((h) => !h.exact));

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const mark = el.querySelector<HTMLElement>("mark");
    if (!mark) return;
    const top = Math.max(0, el.scrollTop + mark.getBoundingClientRect().top - el.getBoundingClientRect().top - 16);
    if (reduced || typeof el.scrollTo !== "function") el.scrollTop = top;
    else el.scrollTo({ top, behavior: "smooth" });
    // once per page drawn
  }, [passage.page_text, passage.text_changed, reduced]);

  return (
    <section className={s.passageView} aria-label={P.title} data-ui="passage-view">
      {showHeading ? <h3 className={s.passageHeading}>{P.title}</h3> : null}
      {passage.text_changed ? (
        <TextChangedNote />
      ) : (
        <>
          <p className={s.hint}>{P.where(passage.page, passage.page_count)}</p>
          <div className={s.passageBox}>
            <ScrollBox label={P.box} ref={box}>
              <p className={s.pageText}>
                {runs.map((r, i) =>
                  r.passage || r.quote ? (
                    <mark key={i} className={r.quote ? s.quoteMark : s.passageMark} data-kind={r.quote ? "quote" : "passage"}>
                      {r.text}
                    </mark>
                  ) : (
                    <span key={i}>{r.text}</span>
                  ),
                )}
              </p>
            </ScrollBox>
          </div>
          {hasPassage || hasQuote ? (
            <p className={s.legend}>
              {hasPassage ? <span>{P.legendPassage}</span> : null}
              {hasPassage && hasQuote ? " " : null}
              {hasQuote ? <span>{P.legendQuote}</span> : null}
            </p>
          ) : null}
          {inexact ? <p className={s.hint}>{P.notExact}</p> : null}
        </>
      )}
    </section>
  );
}

/** The passage of one source of the reader's own answer, fetched once (decision 12); a 404 says it cannot be shown.
 * `card` (the court-record view, decision 13): drawn as a card titled "The Cited Passage", and no card at all on a
 * 404 or when the passage belongs to another order than the one on the page (`orderId`: an edited `s` in the address
 * must never show one order's passage under another order's record). */
export function CitedPassage({
  messageId,
  label,
  card = false,
  orderId,
}: {
  messageId: string;
  label: string;
  card?: boolean;
  /** the order the page shows; a passage of any other order is not drawn */
  orderId?: string;
}) {
  const query = useQuery({
    queryKey: passageKey(messageId, label),
    queryFn: () =>
      api<AssistantPassage>(`/assistant/messages/${encodeURIComponent(messageId)}/sources/${encodeURIComponent(label)}/passage`),
    staleTime: Infinity,
    retry: false,
  });
  const missing = query.error instanceof ApiError && query.error.status === 404;
  if (card && missing) return null;
  if (orderId !== undefined && query.data && query.data.order_id !== orderId) return null;
  const body = query.isPending ? (
    <Loading lines={3} />
  ) : missing ? (
    <p className={s.muted}>{P.cannotShow}</p>
  ) : query.error || !query.data ? (
    <ErrorBanner error={query.error} onRetry={() => void query.refetch()} />
  ) : (
    <PassageView passage={query.data} showHeading={!card} />
  );
  return card ? <Card title={P.title}>{body}</Card> : body;
}
