"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Check } from "@/components/ui/Field";
import { Card, PageHeader } from "@/components/ui/Layout";
import { Pagination } from "@/components/ui/Pagination";
import { Pill } from "@/components/ui/Pill";
import { Async, Empty, Loading } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { api } from "@/lib/api";
import { fmtDateTime, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Notification, Page } from "@/lib/types";
import { useUrlState } from "@/lib/urlState";

function NotificationsInner() {
  const url = useUrlState();
  const toast = useToast();
  const unread = url.get("unread") === "true";
  const page = Number(url.get("page", "1")) || 1;
  const state = useApi<Page<Notification>>("/notifications", { unread: unread || undefined, page, size: 25 });
  const [busy, setBusy] = useState<string | null>(null);

  const markRead = async (id: string) => {
    setBusy(id);
    try {
      await api.post(`/notifications/${id}/read`);
      state.reload();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  };

  const markAll = async () => {
    setBusy("all");
    try {
      await api.post("/notifications/read-all");
      toast.success("All notifications marked as read.");
      state.reload();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Notifications"
        sub="Messages sent to you in the portal. E-mail and SMS copies follow your preferences in Settings."
        actions={
          <Button onClick={markAll} busy={busy === "all"} icon="check">
            Mark all read
          </Button>
        }
      />
      <div>
        <Check label="Unread only" checked={unread} onChange={(e) => url.set({ unread: e.target.checked, page: null })} />
      </div>
      <Async state={state} loadingLabel="Loading notifications">
        {(p) =>
          p.items.length === 0 ? (
            <Empty title={unread ? "No unread notifications" : "No notifications yet"} center />
          ) : (
            <>
              <Card>
                <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                  {p.items.map((n, i) => (
                    <li
                      key={n.id}
                      style={{
                        display: "flex",
                        gap: 14,
                        alignItems: "flex-start",
                        padding: "14px 0",
                        borderTop: i === 0 ? "none" : "1px solid var(--border)",
                        flexWrap: "wrap",
                      }}
                    >
                      <div style={{ flexGrow: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 3, flexBasis: 300 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                          {!n.read_at ? <Pill tone="info">New</Pill> : null}
                          <strong>{n.title}</strong>
                        </div>
                        {n.body ? <span className="muted" style={{ fontSize: 14 }}>{n.body}</span> : null}
                        <span className="muted" style={{ fontSize: 12 }}>
                          {fmtDateTime(n.created_at)} · {humanize(n.channel)}
                          {n.read_at ? ` · read ${fmtDateTime(n.read_at)}` : ""}
                        </span>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        {n.case_id ? (
                          <Link href={`/cases/${n.case_id}`} style={{ fontSize: 14, fontWeight: 600 }}>
                            Open case
                          </Link>
                        ) : n.alert_id ? (
                          <Link href="/alerts" style={{ fontSize: 14, fontWeight: 600 }}>
                            Alerts
                          </Link>
                        ) : null}
                        {!n.read_at ? (
                          <Button small busy={busy === n.id} onClick={() => markRead(n.id)} aria-label={`Mark "${n.title}" as read`}>
                            Mark read
                          </Button>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
              <Pagination page={p.page} size={p.size} total={p.total} onPage={(n) => url.set({ page: n > 1 ? n : null })} noun="notifications" />
            </>
          )
        }
      </Async>
    </>
  );
}

export default function NotificationsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <NotificationsInner />
    </Suspense>
  );
}
