"use client";

/**
 * The Access token card and modal (design system-health-inspector, decision 10). The card sits at the top of "Court
 * connections" and shows the token's state read with no call (held and minutes left, or why not); it opens the modal
 * at `?api=token` with the tabs Token, Request and Documentation. The state is read when the screen and the modal
 * open, on window focus and every 60 s while visible. "Check token · 1 token request" is the modal's only primary
 * button: one token request, refused with the wait when not allowed. The token value is never shown.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { Badge, Button, CodeBlock, ErrorBanner, KvList, Lead, Loading, Modal } from "@/components/ui";
import { api } from "@/lib/api/client";
import type { NapixToken, NapixTokenCheck } from "@/lib/api/types";
import { formatDateTime, formatNumber, formatTime } from "@/lib/format";
import { CONSOLE_ERRORS, errorText, T } from "@/lib/messages";
import { secondsUntil, tokenLine, toneOf } from "@/lib/systemHealth";

import { DocsView, HelpLink, ModalTabs } from "./Console";
import s from "./system.module.css";

export const TOKEN_KEY = ["system-health", "token"] as const;
export const TOKEN_POLL_MS = 60_000;
export const TOKEN_TABS = ["token", "request", "docs"] as const;
export type TokenTab = (typeof TOKEN_TABS)[number];
const K = T.system.token;

export function useToken() {
  return useQuery({
    queryKey: TOKEN_KEY,
    queryFn: () => api<NapixToken>("/admin/system-health/token"),
    refetchInterval: TOKEN_POLL_MS,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
}

export function TokenCard({ token, onOpen }: { token: NapixToken | undefined; onOpen: () => void }) {
  return (
    <article
      className={`${s.card} ${s.tokenCard}`}
      data-status={token?.status ?? "unknown"}
      data-testid="token-card"
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("button")) return;
        onOpen();
      }}
    >
      <div className={s.cardHead}>
        <Lead>
          <Badge tone={toneOf(token?.status)}>{token ? K.status[token.status] : T.loading}</Badge>
        </Lead>
        <h3 className={s.cardName}>
          <button type="button" className={s.nameButton} onClick={onOpen} aria-label={K.open}>
            {K.card}
          </button>
        </h3>
      </div>
      <p className={s.muted}>{token ? tokenLine(token) : T.loading}</p>
    </article>
  );
}

function TokenFacts({ token }: { token: NapixToken }) {
  const notYet = K.notYet;
  const held = token.held
    ? token.renewing_soon
      ? K.renewing
      : K.held(Math.max(0, Math.round((token.ttl_seconds ?? 0) / 60)), token.valid_until ? formatTime(token.valid_until) : "—")
    : !token.shared_store
      ? K.noStore
      : K.none;
  const last = token.last_request;
  const items: [string, string][] = [
    [K.card, held],
    [K.issued, token.obtained_at ? formatDateTime(token.obtained_at) : notYet],
    [K.expires, token.expires_at ? formatDateTime(token.expires_at) : notYet],
    [K.typeScope, token.token_type || token.scope ? `${token.token_type ?? "—"}, ${token.scope ?? "—"}` : notYet],
    [
      K.accepted,
      token.accepted_since
        ? K.acceptedYes(formatTime(token.accepted_since.at), token.accepted_since.api_label, token.accepted_since.http_status)
        : token.obtained_at
          ? K.acceptedNo
          : notYet,
    ],
    [K.rejected, formatNumber(token.rejected_since)],
    [
      K.lastRenewal,
      last
        ? [
            formatDateTime(last.at ?? ""),
            last.outcome ?? "",
            last.duration_ms == null ? "" : `${formatNumber(last.duration_ms)} ms`,
            last.rate_limit.limit == null && last.rate_limit.remaining == null
              ? T.system.console.noRate
              : T.system.console.rateValue(String(last.rate_limit.limit ?? "—"), String(last.rate_limit.remaining ?? "—")),
          ]
            .filter(Boolean)
            .join(" · ")
        : notYet,
    ],
    [K.lastFailure, token.last_failure ? `${formatDateTime(token.last_failure.at ?? "")} · ${token.last_failure.family ?? ""}` : "—"],
    [K.requestsToday, formatNumber(token.requests_today)],
  ];
  return (
    <div className="stack">
      <p className={s.outcome}>
        <Badge tone={toneOf(token.status)}>{K.status[token.status]}</Badge>
        {!token.napix_enabled ? <span className={s.muted}> {K.off}</span> : null}
      </p>
      <KvList items={items} />
      <p className={s.muted}>{K.neverShown}</p>
    </div>
  );
}

function TokenRequest({ token }: { token: NapixToken }) {
  const e = token.endpoint;
  return (
    <div className="stack">
      <CodeBlock label={K.method} copySize="md">{`${e.method} ${e.url}`}</CodeBlock>
      <KvList
        items={[
          [K.body, <span key="b" className={s.mono}>{e.body}</span>],
          [K.contentType, <span key="c" className={s.mono}>{e.content_type}</span>],
          [K.auth, e.auth_note],
        ]}
      />
      <CodeBlock label={K.curl} copySize="md">{token.curl_token}</CodeBlock>
    </div>
  );
}

export function TokenModal({ tab, onTab, onClose }: { tab: TokenTab; onTab: (tab: TokenTab) => void; onClose: () => void }) {
  const qc = useQueryClient();
  const token = useToken();
  const [checked, setChecked] = useState<NapixTokenCheck | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  async function check() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const out = await api<NapixTokenCheck>("/admin/system-health/token/check", { method: "POST" });
      setChecked(out);
      qc.setQueryData(TOKEN_KEY, out.token);
    } catch (err) {
      setError(err);
      void qc.invalidateQueries({ queryKey: TOKEN_KEY });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  const t = token.data;
  const wait = t?.check.next_allowed_at ? secondsUntil(t.check.next_allowed_at) : 0;
  const block = !t ? T.loading : t.check.allowed ? null : (t.check.reason ?? (wait ? T.system.nextIn(wait) : null));
  const footer = (
    <div className={s.footer}>
      {block ? (
        <span id="token-check-reason" className={s.reason}>
          {block}
        </span>
      ) : null}
      <Button busy={busy} disabled={!!block} aria-describedby={block ? "token-check-reason" : undefined} onClick={() => void check()}>
        {K.check}
      </Button>
    </div>
  );
  const header = (
    <div className={s.modalHeader}>
      <span className={s.muted}>{t ? `${t.endpoint.method} ${t.endpoint.url}` : ""}</span>
      <HelpLink doc="subscriber_manual" page={10} label={K.help} />
    </div>
  );
  return (
    <Modal open title={K.card} onClose={onClose} header={header} footer={footer}>
      <ErrorBanner error={token.error} onRetry={() => void token.refetch()} retrySize="md" />
      {token.isPending ? <Loading lines={3} /> : null}
      {t ? (
        <ModalTabs tabs={TOKEN_TABS} labels={K.tabs} active={tab} onSelect={onTab} label={K.card} idPrefix="token">
          {checked ? (
            <p className={s.resultWord} role="status">
              {K.checked(checked.outcome ?? (checked.ok ? "obtained" : "failed"))}
            </p>
          ) : null}
          {error ? (
            <p className={s.error} role="alert">
              {errorText(error, CONSOLE_ERRORS)}
            </p>
          ) : null}
          {tab === "token" ? <TokenFacts token={t} /> : null}
          {tab === "request" ? <TokenRequest token={t} /> : null}
          {tab === "docs" ? <DocsView apiKey="token" /> : null}
        </ModalTabs>
      ) : null}
    </Modal>
  );
}
