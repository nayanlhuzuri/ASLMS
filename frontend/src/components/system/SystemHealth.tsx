"use client";

/**
 * The System health screen (design api-health-checker, decisions 2-15), for holders of `admin.service_health`: the
 * overview band (the court cards' 24 h answered rate in a ring, the overall sentence computed by the server and four
 * headline figures), the Access token card and the 17 court API cards in four groups read from the call log, and the
 * ten ASLMS service checks. Reading never calls the court. A card shows status and history only and makes no call;
 * clicking it opens that API's request console in a large modal (`?api=<key>&tab=…`, so Back closes it; closing goes
 * back when this page opened it: `useUrlOverlay`, design portal-ui-polish, decision 10), where "Send · 1 court call"
 * makes the one call (design system-health-inspector, decision 1). The Access token card opens `?api=token` (decision
 * 10). The court cards are read again every minute while the page is visible and after each send; the services when
 * the page opens, on "Check services again" (the page's one primary button) and on window focus. People are never
 * named: calls read "background work", "a person" or "your test". The Court Calls section (design
 * data-collection-redesign, decision 3) follows the services for holders of a health-reader function as well.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  Badge,
  Button,
  Card,
  Collapsible,
  ErrorBanner,
  Kpi,
  KvList,
  Lead,
  ListRow,
  Loading,
  Notice,
  PageHeader,
  RateRing,
  SparkBars,
} from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { ApiCard, ServicesHealth, SystemHealth as SystemHealthData } from "@/lib/api/types";
import { formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import { queryString, type Params } from "@/lib/params";
import { showsCourtCalls } from "@/lib/routes";
import { cardsOf, courtTotals, percent, ringTone, toneOf, typicalMs } from "@/lib/systemHealth";
import { useUrlOverlay } from "@/lib/useUrlOverlay";

import { CONSOLE_TABS, ConsoleModal, type ConsoleTab } from "./Console";
import { CourtCalls } from "./CourtCalls";
import s from "./system.module.css";
import { TOKEN_TABS, TokenCard, TokenModal, useToken, type TokenTab } from "./Token";

export const SUMMARY_KEY = ["system-health"] as const;
export const SERVICES_KEY = ["system-health", "services"] as const;
export const SUMMARY_POLL_MS = 60_000;
const TOKEN = "token"; // a reserved key, never a court API

function tabOf<K extends string>(tabs: readonly K[], value: string | undefined): K {
  return (tabs as readonly string[]).includes(value ?? "") ? (value as K) : tabs[0]!;
}

export function SystemHealth({ params }: { params: Params }) {
  const me = useMe();
  const overlay = useUrlOverlay("api", params, "/system", ["tab"]);
  const qc = useQueryClient();
  const summary = useQuery({
    queryKey: SUMMARY_KEY,
    queryFn: () => api<SystemHealthData>("/admin/system-health"),
    refetchInterval: SUMMARY_POLL_MS,
  });
  const services = useQuery({
    queryKey: SERVICES_KEY,
    queryFn: () => api<ServicesHealth>("/admin/system-health/services"),
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
  const token = useToken();
  const openKey = params.api ?? null;
  const cards = cardsOf(summary.data);
  const openCard = cards.find((c) => c.key === openKey) ?? null;
  // the tab lives in the address (a shared link opens it) without a new history entry, so Back still closes; a
  // tab chosen in this overlay wins over the address it was opened with
  const [chosen, setChosen] = useState<{ key: string | null; tab: string } | null>(null);
  const tab = chosen && chosen.key === openKey ? chosen.tab : params.tab;

  function open(key: string) {
    overlay.open(key, { tab: key === TOKEN ? TOKEN_TABS[0] : CONSOLE_TABS[0] });
  }
  function close() {
    overlay.close();
  }
  function selectTab(next: string) {
    setChosen({ key: openKey, tab: next });
    if (typeof window === "undefined" || !openKey) return;
    const state = (window.history.state as Record<string, unknown> | null) ?? {};
    window.history.replaceState(state, "", "/system" + queryString({ ...params, api: openKey, tab: next }));
  }

  return (
    <div className="stack">
      <PageHeader
        title={T.system.title}
        subtitle={summary.data ? T.system.subtitle(formatTime(summary.data.as_of)) : undefined}
        primary={
          <Button onClick={() => void services.refetch()} busy={services.isFetching}>
            {T.system.checkAgain}
          </Button>
        }
      />
      <ErrorBanner error={summary.error} onRetry={() => void summary.refetch()} />
      {summary.isPending ? <Loading /> : null}
      {summary.data && !summary.data.napix_enabled ? <Notice>{T.system.switchedOff}</Notice> : null}
      {summary.data ? <Overview data={summary.data} services={services.data} /> : null}
      {summary.data ? (
        <section className="stack" id="court" aria-labelledby="court-heading">
          <div className={s.sectionHead}>
            <h2 id="court-heading">{T.system.court}</h2>
            <span className="muted">{T.system.courtCount(summary.data.summary.working, summary.data.summary.total)}</span>
          </div>
          <TokenCard token={token.data} onOpen={() => open(TOKEN)} />
          {summary.data.groups.map((g) => (
            <section key={g.key} className="stack" aria-labelledby={`group-${g.key}`}>
              <h3 id={`group-${g.key}`}>{T.system.groups[g.key] ?? g.label}</h3>
              <div className={s.grid}>
                {g.cards.map((c) => (
                  <CourtCard key={c.key} card={c} onOpen={() => open(c.key)} />
                ))}
              </div>
            </section>
          ))}
        </section>
      ) : null}
      <Services query={services} />
      {showsCourtCalls(me.data) ? <CourtCalls /> : null}
      {summary.data && openCard ? (
        <ConsoleModal
          apiKey={openCard.key}
          card={openCard}
          napixEnabled={summary.data.napix_enabled}
          tab={tabOf<ConsoleTab>(CONSOLE_TABS, tab)}
          onTab={selectTab}
          onClose={close}
          onSent={() => void qc.invalidateQueries({ queryKey: SUMMARY_KEY })}
        />
      ) : null}
      {openKey === TOKEN ? <TokenModal tab={tabOf<TokenTab>(TOKEN_TABS, tab)} onTab={selectTab} onClose={close} /> : null}
    </div>
  );
}

function Overview({ data, services }: { data: SystemHealthData; services: ServicesHealth | undefined }) {
  const cards = cardsOf(data);
  const totals = courtTotals(cards);
  const typical = typicalMs(cards);
  const overall = services?.overall;
  const n = overall ? (overall.sentence_key === "not_working" ? overall.counts.not_working : overall.counts.attention) : 0;
  const sentence = (T.system.sentence[overall?.sentence_key ?? "not_known"] ?? T.system.sentence.not_known!)(n);
  const window = data.window;
  return (
    <Card title={T.system.overview}>
      <div className={s.band}>
        <RateRing
          value={totals.rate}
          tone={ringTone(totals.rate)}
          label={totals.rate === null ? T.system.ringNone : T.system.ringLabel(percent(totals.rate))}
        >
          {totals.rate === null ? (
            <span className="muted">{T.system.ringNone}</span>
          ) : (
            <>
              <b className={s.ringValue}>{percent(totals.rate)}</b>
              <span>{T.system.answered.toLowerCase()}</span>
            </>
          )}
        </RateRing>
        <div className={s.bandBody}>
          <p className={s.sentence} aria-live="polite">
            {overall ? <Badge tone={toneOf(overall.status)}>{T.system.serviceStatus[overall.status]}</Badge> : null}{" "}
            {sentence}
          </p>
          <div className={s.kpis}>
            <Kpi
              label={T.system.kpi.answered}
              value={totals.answered}
              sub={T.system.kpiSub.answered(formatNumber(totals.calls))}
            />
            <Kpi label={T.system.kpi.median} value={typical} sub={T.system.kpiSub.median} />
            <Kpi
              label={T.system.kpi.left}
              value={window.remaining ?? null}
              sub={
                window.remaining === null || window.remaining === undefined
                  ? T.system.kpiSub.leftUnknown
                  : window.next_reset_at
                    ? T.system.kpiSub.resets(formatTime(window.next_reset_at))
                    : undefined
              }
            />
            <Kpi
              label={T.system.kpi.services}
              value={overall ? overall.counts.services_working : null}
              sub={overall ? T.system.kpiSub.services(overall.counts.services_total) : undefined}
              tone={overall && overall.counts.not_working > 0 ? "danger" : undefined}
            />
          </div>
        </div>
      </div>
    </Card>
  );
}

/** A court API's card: status and history from the call log, no call; clicking it opens the console. */
function CourtCard({ card, onOpen }: { card: ApiCard; onOpen: () => void }) {
  const name = T.system.apis[card.key] ?? card.label;
  const answered = card.hours.reduce((n, h) => n + h.answered, 0);
  const failed = card.hours.reduce((n, h) => n + h.failed, 0);
  return (
    <article
      className={s.card}
      data-status={card.status}
      data-testid={`card-${card.key}`}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("button")) return;
        onOpen();
      }}
    >
      <div className={s.cardHead}>
        <Lead>
          <Badge tone={toneOf(card.status)}>{T.system.status[card.status] ?? card.status_word}</Badge>
        </Lead>
        <h4 className={s.cardName}>
          <button type="button" className={s.nameButton} onClick={onOpen} aria-label={T.system.open(name)}>
            {name}
          </button>
        </h4>
      </div>
      <p className={s.muted}>
        {card.last_call
          ? T.system.lastCall(formatTime(card.last_call.called_at), formatNumber(card.last_call.duration_ms))
          : T.system.noCall}
      </p>
      <SparkBars buckets={card.hours} label={T.system.bars(answered, failed)} />
      <p className={s.figures}>
        <span>{T.system.rate24(percent(card.h24.rate))}</span>
        <span>{T.system.rate7(percent(card.d7.rate))}</span>
      </p>
    </article>
  );
}

function Services({ query }: { query: { data?: ServicesHealth; error: unknown; isPending: boolean; refetch: () => unknown } }) {
  const data = query.data;
  return (
    <section className="stack" id="services" aria-labelledby="services-heading">
      <div className={s.sectionHead}>
        <h2 id="services-heading">{T.system.services}</h2>
        {data ? (
          <span className="muted">
            {T.system.servicesCount(data.overall.counts.services_working, data.overall.counts.services_total)}
          </span>
        ) : null}
      </div>
      <ErrorBanner error={query.error} onRetry={() => void query.refetch()} />
      {query.isPending ? <Loading /> : null}
      {data ? (
        <Card flush>
          <ul className={s.services}>
            {data.services.map((x) => (
              <ListRow
                key={x.key}
                as="li"
                lead={
                  <Lead>
                    <Badge tone={toneOf(x.status)}>{T.system.serviceStatus[x.status]}</Badge>
                  </Lead>
                }
                trail={<span className={s.ms}>{`${formatNumber(x.duration_ms)} ${T.system.ms}`}</span>}
              >
                <Collapsible
                  summary={
                    <span className={s.serviceLine}>
                      <b>{T.system.labels[x.key] ?? x.label}</b> <span className={s.muted}>{x.headline}</span>
                    </span>
                  }
                >
                  {x.facts.length > 0 ? <KvList items={x.facts.map((f) => [f.label, f.value])} /> : <p className={s.muted}>{x.headline}</p>}
                </Collapsible>
              </ListRow>
            ))}
          </ul>
        </Card>
      ) : null}
    </section>
  );
}
