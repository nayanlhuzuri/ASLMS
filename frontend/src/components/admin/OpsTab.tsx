"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { fmtDateTime, humanize, todayIST } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { JOBS } from "@/lib/labels";
import type { Failure, Ok } from "@/lib/types";
import { Button } from "../ui/Button";
import { Check, Field, TextInput } from "../ui/Field";
import { Card, CardHead } from "../ui/Layout";
import { Async, Empty } from "../ui/States";
import { DataTable } from "../ui/Table";
import { useToast } from "../ui/Toast";
import s from "./admin.module.css";

export function OpsTab() {
  const toast = useToast();
  const [openOnly, setOpenOnly] = useState(true);
  const failures = useApi<Failure[]>("/ops/failures", { open_only: openOnly });
  const [resolving, setResolving] = useState<string | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [listDate, setListDate] = useState(todayIST());

  const resolve = async (f: Failure) => {
    setResolving(f.id);
    try {
      await api.post(`/ops/failures/${f.id}/resolve`);
      toast.success("Failure marked resolved.");
      failures.reload();
    } catch (e) {
      toast.error(e);
    } finally {
      setResolving(null);
    }
  };

  const run = async (job: string, needsDate?: boolean) => {
    setRunning(job);
    try {
      const res = await api.post<Ok>("/ops/jobs", { job, list_date: needsDate ? listDate : null });
      toast.success(`Job queued${res?.detail ? ` (task ${res.detail})` : ""}. Its result appears under Reports, Data collection health.`);
    } catch (e) {
      toast.error(e);
    } finally {
      setRunning(null);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <Card labelledBy="jobs-h">
        <CardHead id="jobs-h" title="Run a job" />
        <p className={s.hint}>Jobs run on the background workers. Every run is recorded in the audit log.</p>
        <div className={s.jobs}>
          {JOBS.map((j) => (
            <div key={j.value} className={s.job}>
              <strong>{j.label}</strong>
              {j.needsDate ? (
                <Field label="Cause-list date">
                  <TextInput type="date" value={listDate} onChange={(e) => setListDate(e.target.value)} />
                </Field>
              ) : null}
              <div>
                <Button small busy={running === j.value} onClick={() => run(j.value, j.needsDate)}>
                  Run
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
      <Card labelledBy="fail-h">
        <CardHead id="fail-h" title="Data source failures" actions={<Check label="Open only" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />} />
        <Async state={failures} loadingLabel="Loading failures">
          {(rows) =>
            rows.length === 0 ? (
              <Empty title={openOnly ? "No open failures" : "No failures recorded"} />
            ) : (
              <DataTable
                bare
                caption="Data source failures"
                rows={rows}
                rowKey={(f) => f.id}
                columns={[
                  { key: "kind", header: "Kind", render: (f) => humanize(f.kind) },
                  { key: "ref", header: "Reference", mono: true, render: (f) => f.ref },
                  { key: "error", header: "Error", render: (f) => <span style={{ fontSize: 13, overflowWrap: "anywhere" }}>{f.error}</span> },
                  { key: "attempts", header: "Attempts", num: true, render: (f) => String(f.attempts) },
                  { key: "last", header: "Last seen", render: (f) => fmtDateTime(f.last_seen) },
                  {
                    key: "act",
                    header: "",
                    actions: true,
                    render: (f) =>
                      f.resolved_at ? (
                        <span className="muted" style={{ fontSize: 13 }}>
                          Resolved {fmtDateTime(f.resolved_at)}
                        </span>
                      ) : (
                        <Button small busy={resolving === f.id} onClick={() => resolve(f)}>
                          Resolve
                        </Button>
                      ),
                  },
                ]}
              />
            )
          }
        </Async>
      </Card>
    </div>
  );
}
