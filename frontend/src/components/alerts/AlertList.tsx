"use client";

/**
 * The caller's alerts (design portal-files-alerts, decisions 5-9; portal-workflow decision 16; plan §5.5, §5.12):
 * `GET /alerts` newest first, paged by 50, with the counts of `/alerts/counts` above. Filters live in the query string
 * and go to the API as its parameters. Opening the list marks nothing read; a row is marked read by "Mark read", by
 * "Mark all read", or by following its subject link (marked first; a failed mark never blocks the navigation).
 * Acknowledge / Done show by the item's `can_act` and status; a case is a link only when the API's `case_visible`
 * says the caller can open it. The one filter bar (design portal-filters): the shared case filters with the owning
 * department, plus the alert status, kind, severity and Unread only; with any case filter set the alerts without a case
 * drop out, and the bar says so.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { FilterBar } from "@/components/filters/FilterBar";
import { useFilters } from "@/components/inbox/common";
import {
  Badge,
  Button,
  CaseLink,
  EmptyState,
  ErrorBanner,
  Loading,
  Pagination,
  SeverityBadge,
} from "@/components/ui";
import { AlertActions } from "@/components/workflow/CaseAlerts";
import { api } from "@/lib/api/client";
import { useAlertCounts, useLabels } from "@/lib/api/hooks";
import type { AlertItem, AlertList as AlertListOut } from "@/lib/api/types";
import { hasCaseFilter, toApiQuery } from "@/lib/filters";
import { formatDateTime, formatNumber } from "@/lib/format";
import { T } from "@/lib/messages";
import { offsetOf, PAGE, type Params } from "@/lib/params";
import { casePath, refPath } from "@/lib/refs";
import { useAction } from "@/lib/useAction";

import { AlertLink, AnswerIt, markRead, useAlertRefresh } from "./AlertLink";

import cs from "@/components/case/case.module.css";

const STATUSES = ["", "open", "acknowledged", "done", "expired", "all"] as const;
const SEVERITIES = ["critical", "high", "normal"] as const;

/** Decision 8: the case link (only with `case_visible`), the case as text with a line, a ticket link, or nothing. */
export function AlertSubject({ alert }: { alert: AlertItem }) {
  if (alert.case) {
    if (alert.case_visible) {
      return (
        <AlertLink alert={alert} href={casePath(alert.case.ref_no)} className="mono">
          <span title={alert.case.cnr ?? undefined}>{alert.case.case_no_text || alert.case.ref_no}</span>
        </AlertLink>
      );
    }
    return (
      <span>
        <CaseLink value={alert.case} visible={false} /> <span className="muted">{T.alerts.noLongerVisible}</span>
      </span>
    );
  }
  if (alert.ticket_ref) {
    return (
      <AlertLink alert={alert} href={`/admin/tickets/${encodeURIComponent(refPath(alert.ticket_ref))}`}>
        {T.alerts.ticket(alert.ticket_ref)}
      </AlertLink>
    );
  }
  return null;
}

function AlertRow({ alert }: { alert: AlertItem }) {
  const refresh = useAlertRefresh();
  const action = useAction();
  return (
    <li className={cs.note}>
      <div className={cs.noteHead}>
        <SeverityBadge severity={alert.severity} />
        <strong>{alert.kind_label}</strong>
        <span>{T.wf.alertStatus[alert.status] ?? alert.status}</span>
        <span className="mono muted">{alert.ref_no}</span>
        {alert.read_at ? null : (
          <Badge tone="warning">
            {T.alerts.newBadge}
            <span className="visually-hidden"> {T.alerts.unreadHidden}</span>
          </Badge>
        )}
      </div>
      <div>
        <strong>{alert.title}</strong>
      </div>
      {alert.body ? <p className={cs.noteBody}>{alert.body}</p> : null}
      <div className="row">
        <AlertSubject alert={alert} />
        <AnswerIt alert={alert} />
        {alert.due_at ? <span>{T.wf.dueAt(formatDateTime(alert.due_at))}</span> : null}
      </div>
      <div className="muted">
        {alert.notified_at ? T.alerts.notifiedAt(formatDateTime(alert.notified_at)) : null}
        {alert.read_at ? ` · ${T.alerts.readAt(formatDateTime(alert.read_at))}` : null}
      </div>
      {alert.acknowledged_by && alert.acknowledged_at ? (
        <div className="muted">{T.wf.acknowledgedBy(alert.acknowledged_by.full_name, formatDateTime(alert.acknowledged_at))}</div>
      ) : null}
      <ErrorBanner error={action.error} />
      <div className="row">
        {alert.read_at ? null : (
          <Button
            variant="secondary"
            busy={action.busy}
            onClick={async () => {
              await action.run(() => markRead([alert.id]));
              await refresh(alert);
            }}
          >
            {T.alerts.markRead}
          </Button>
        )}
        <AlertActions alert={alert} onChanged={() => refresh(alert)} />
      </div>
    </li>
  );
}

function CountsHeader() {
  const counts = useAlertCounts();
  const refresh = useAlertRefresh();
  const action = useAction();
  if (!counts.data) return <ErrorBanner error={counts.error} onRetry={() => counts.refetch()} />;
  const c = counts.data;
  return (
    <div className="row" aria-label={T.alerts.counts} role="group">
      <strong>{T.alerts.unread(formatNumber(c.unread))}</strong>
      {SEVERITIES.map((sev) => (
        <span key={sev}>{T.alerts.open(T.wf.severity[sev] ?? sev, formatNumber(c.open[sev]))}</span>
      ))}
      {c.unread > 0 ? (
        <Button
          variant="secondary"
          busy={action.busy}
          onClick={async () => {
            await action.run(() => markRead("all"));
            await refresh();
          }}
        >
          {T.alerts.markAllRead}
        </Button>
      ) : null}
      <ErrorBanner error={action.error} />
    </div>
  );
}

export function AlertList({ params }: { params: Params }) {
  const setFilters = useFilters(params);
  const labels = useLabels();
  const offset = offsetOf(params);
  const caseFilters = toApiQuery(params, "alerts");
  const filters = {
    status: params.status || undefined,
    kind: params.kind || undefined,
    severity: params.severity || undefined,
    unread: params.unread === "true" ? true : undefined,
    ...caseFilters,
    offset,
  };
  const list = useQuery({
    queryKey: ["alerts", "list", filters],
    queryFn: () => api<AlertListOut>("/alerts", { query: { ...filters, limit: PAGE } }),
    placeholderData: keepPreviousData,
  });
  const defaults =
    !filters.status && !filters.kind && !filters.severity && !filters.unread && offset === 0 && !hasCaseFilter(params, "alerts");
  return (
    <div className="stack">
      <CountsHeader />
      <FilterBar
        list="alerts"
        params={params}
        own={[
          {
            key: "status",
            kind: "select",
            label: T.alerts.status,
            options: STATUSES.filter((st) => st).map((st) => ({ value: st, label: T.alerts.statuses[st] ?? st })),
            placeholder: T.alerts.statuses[""],
          },
          {
            key: "kind",
            kind: "select",
            label: T.alerts.kind,
            placeholder: T.alerts.allKinds,
            options: (labels.data?.alert_kinds ?? []).map((k) => ({ value: k.code, label: k.label })),
            more: true,
          },
          {
            key: "severity",
            kind: "select",
            label: T.alerts.severity,
            placeholder: T.alerts.allSeverities,
            options: SEVERITIES.map((sev) => ({ value: sev, label: T.wf.severity[sev] ?? sev })),
            more: true,
          },
          { key: "unread", kind: "check", label: T.alerts.unreadOnly, more: true },
        ]}
        total={list.data?.total}
        noun="alerts"
        note={hasCaseFilter(params, "alerts") ? T.filters.caselessHidden : null}
      />
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.isPending ? <Loading /> : null}
      {list.data ? (
        list.data.items.length === 0 ? (
          <EmptyState>{defaults ? T.alerts.emptyDefault : T.alerts.empty}</EmptyState>
        ) : (
          <>
            <ul className="stack" style={{ listStyle: "none", padding: 0 }} aria-label={T.alerts.list}>
              {list.data.items.map((a) => (
                <AlertRow key={a.id} alert={a} />
              ))}
            </ul>
            <Pagination offset={offset} limit={PAGE} total={list.data.total} onChange={(o) => setFilters({ offset: String(o) })} />
          </>
        )
      ) : null}
    </div>
  );
}
