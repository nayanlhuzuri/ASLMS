"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { HearingCalendar } from "@/components/alerts/HearingCalendar";
import { useMe } from "@/components/shell/MeContext";
import { Button } from "@/components/ui/Button";
import { Field, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/Layout";
import { Pagination } from "@/components/ui/Pagination";
import { AlertStatusPill, SeverityPill } from "@/components/ui/Pill";
import { Async, Empty, Loading } from "@/components/ui/States";
import { DataTable } from "@/components/ui/Table";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { ALERT_KIND_OPTIONS, alertKindLabel } from "@/lib/labels";
import type { Alert, Page } from "@/lib/types";
import { useUrlState } from "@/lib/urlState";

function AlertList() {
  const { me } = useMe();
  const url = useUrlState();
  const toast = useToast();
  const status = url.get("status", "open");
  const kind = url.get("kind");
  const severity = url.get("severity");
  const page = Number(url.get("page", "1")) || 1;
  const state = useApi<Page<Alert>>("/alerts", { status: status === "all" ? undefined : status, kind: kind || undefined, severity: severity || undefined, page, size: 25 });
  const [busy, setBusy] = useState<string | null>(null);

  const act = async (a: Alert, action: "ack" | "done") => {
    setBusy(a.id);
    try {
      await api.post(`/alerts/${a.id}/${action}`);
      toast.success(action === "ack" ? "Alert acknowledged." : "Alert marked done.");
      state.reload();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <Field label="Status">
          <Select value={status} onChange={(e) => url.set({ status: e.target.value === "open" ? null : e.target.value, page: null })}>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="done">Done</option>
            <option value="expired">Expired</option>
            <option value="all">All</option>
          </Select>
        </Field>
        <Field label="Kind">
          <Select value={kind} onChange={(e) => url.set({ kind: e.target.value, page: null })}>
            <option value="">All kinds</option>
            {ALERT_KIND_OPTIONS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Severity">
          <Select value={severity} onChange={(e) => url.set({ severity: e.target.value, page: null })}>
            <option value="">Any</option>
            <option value="critical">Critical (within 48 hours)</option>
            <option value="high">This week</option>
            <option value="normal">Normal</option>
          </Select>
        </Field>
      </div>
      <Async state={state} loadingLabel="Loading alerts">
        {(p) =>
          p.items.length === 0 ? (
            <Empty title="No alerts" center>
              Alerts are raised from next dates, new orders and hearings in your cases.
            </Empty>
          ) : (
            <>
              <DataTable
                caption="Alerts"
                rows={p.items}
                rowKey={(a) => a.id}
                columns={[
                  { key: "sev", header: "Severity", render: (a) => <SeverityPill severity={a.severity} /> },
                  {
                    key: "title",
                    header: "Alert",
                    render: (a) => (
                      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        {a.case_id ? (
                          <Link href={`/cases/${a.case_id}`} style={{ fontWeight: 600 }}>
                            {a.title}
                          </Link>
                        ) : (
                          <strong>{a.title}</strong>
                        )}
                        {a.body ? <span className="muted" style={{ fontSize: 13 }}>{a.body}</span> : null}
                      </div>
                    ),
                  },
                  { key: "kind", header: "Kind", render: (a) => alertKindLabel(a.kind) },
                  { key: "due", header: "Due", render: (a) => fmtDateTime(a.due_at) },
                  { key: "status", header: "Status", render: (a) => <AlertStatusPill status={a.status} /> },
                  {
                    key: "act",
                    header: "",
                    actions: true,
                    render: (a) => (
                      <span style={{ display: "inline-flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                        {a.status === "open" ? (
                          <Button small busy={busy === a.id} onClick={() => act(a, "ack")}>
                            Acknowledge
                          </Button>
                        ) : null}
                        {!me.read_only && (a.status === "open" || a.status === "acknowledged") ? (
                          <Button small variant="primary" disabled={busy === a.id} onClick={() => act(a, "done")}>
                            Mark done
                          </Button>
                        ) : null}
                      </span>
                    ),
                  },
                ]}
              />
              <Pagination page={p.page} size={p.size} total={p.total} onPage={(n) => url.set({ page: n > 1 ? n : null })} noun="alerts" />
            </>
          )
        }
      </Async>
    </div>
  );
}

function AlertsInner() {
  const url = useUrlState();
  const view = url.get("view", "alerts");
  return (
    <>
      <PageHeader title="Alerts & Calendar" sub="Hearings within 48 hours are critical; hearings this week are highlighted." />
      <Tabs
        tabs={[
          { id: "alerts", label: "Alerts" },
          { id: "calendar", label: "Hearing calendar" },
        ]}
        active={view}
        onChange={(v) => url.set({ view: v === "alerts" ? null : v })}
        label="Alerts and calendar"
        idBase="alerts"
      />
      <TabPanel idBase="alerts" id={view}>
        {view === "calendar" ? <HearingCalendar /> : <AlertList />}
      </TabPanel>
    </>
  );
}

export default function AlertsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AlertsInner />
    </Suspense>
  );
}
