"use client";

/**
 * The System health screen (design api-health-checker, decisions 2-15), for holders of `admin.service_health`: the
 * overview band (the court cards' 24 h answered rate in a ring, the overall sentence computed by the server and four
 * headline figures), the 17 court API cards in four groups read from the call log, and the ten ASLMS service checks.
 * Reading never calls the court; "Test now" makes one court call (its cost is on the button) and opens the card's
 * panel (`?api=<key>`, so Back closes it; closing goes back when this page opened it: `useUrlOverlay`, design
 * portal-ui-polish, decision 10) with the test running. The court cards are read again every minute while
 * the page is visible and after each test; the services when the page opens, on "Check services again" (the page's
 * one primary button) and on window focus. People are never named: calls read "background work", "a person" or
 * "your test".
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

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
import type { ApiCard, ApiTest, ServicesHealth, SystemHealth as SystemHealthData } from "@/lib/api/types";
import { formatNumber, formatTime } from "@/lib/format";
import { T } from "@/lib/messages";
import type { Params } from "@/lib/params";
import { cardsOf, courtTotals, percent, ringTone, toneOf, typicalMs } from "@/lib/systemHealth";
import { useUrlOverlay } from "@/lib/useUrlOverlay";

import { ApiPanel, TestButton, type TestState } from "./ApiPanel";
import s from "./system.module.css";

export const SUMMARY_KEY = ["system-health"] as const;
export const SERVICES_KEY = ["system-health", "services"] as const;
export const SUMMARY_POLL_MS = 60_000;

export function SystemHealth({ params }: { params: Params }) {
  const overlay = useUrlOverlay("api", params, "/system");
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
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const inFlight = useRef<Set<string>>(new Set());
  const openKey = params.api ?? null;
  const cards = cardsOf(summary.data);
  const openCard = cards.find((c) => c.key === openKey) ?? null;

  function open(key: string) {
    overlay.open(key);
  }
  function close() {
    overlay.close();
  }
  async function runTest(key: string) {
    if (inFlight.current.has(key)) return; // a double click sends one request
    inFlight.current.add(key);
    setTests((t) => ({ ...t, [key]: { running: true } }));
    try {
      const result = await api<ApiTest>(`/admin/system-health/napix/${key}/test`, { method: "POST" });
      setTests((t) => ({ ...t, [key]: { running: false, result } }));
    } catch (error) {
      setTests((t) => ({ ...t, [key]: { running: false, error } }));
    } finally {
      inFlight.current.delete(key);
      void qc.invalidateQueries({ queryKey: SUMMARY_KEY });
    }
  }
  function testFromCard(key: string) {
    if (openKey !== key) open(key);
    void runTest(key);
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
        <section className="stack" aria-labelledby="court-heading">
          <div className={s.sectionHead}>
            <h2 id="court-heading">{T.system.court}</h2>
            <span className="muted">{T.system.courtCount(summary.data.summary.working, summary.data.summary.total)}</span>
          </div>
          {summary.data.groups.map((g) => (
            <section key={g.key} className="stack" aria-labelledby={`group-${g.key}`}>
              <h3 id={`group-${g.key}`}>{T.system.groups[g.key] ?? g.label}</h3>
              <div className={s.grid}>
                {g.cards.map((c) => (
                  <CourtCard
                    key={c.key}
                    card={c}
                    napixEnabled={summary.data.napix_enabled}
                    running={!!tests[c.key]?.running}
                    onOpen={() => open(c.key)}
                    onTest={() => testFromCard(c.key)}
                  />
                ))}
              </div>
            </section>
          ))}
        </section>
      ) : null}
      <Services query={services} />
      {summary.data ? (
        <ApiPanel
          apiKey={openKey}
          card={openCard}
          napixEnabled={summary.data.napix_enabled}
          test={openKey ? tests[openKey] : undefined}
          onTest={() => openKey && void runTest(openKey)}
          onClose={close}
        />
      ) : null}
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

function CourtCard({
  card,
  napixEnabled,
  running,
  onOpen,
  onTest,
}: {
  card: ApiCard;
  napixEnabled: boolean;
  running: boolean;
  onOpen: () => void;
  onTest: () => void;
}) {
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
      <TestButton card={card} napixEnabled={napixEnabled} running={running} onTest={onTest} />
    </article>
  );
}

function Services({ query }: { query: { data?: ServicesHealth; error: unknown; isPending: boolean; refetch: () => unknown } }) {
  const data = query.data;
  return (
    <section className="stack" aria-labelledby="services-heading">
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
