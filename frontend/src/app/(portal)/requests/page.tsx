"use client";

import { Suspense } from "react";
import { RequestCard } from "@/components/case/detail/Requests";
import { useMe } from "@/components/shell/MeContext";
import { Field, Select } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/Layout";
import { Pagination } from "@/components/ui/Pagination";
import { Async, Empty, Loading } from "@/components/ui/States";
import { TabPanel, Tabs } from "@/components/ui/Tabs";
import { useApi } from "@/lib/hooks";
import { canUseRequests } from "@/lib/roles";
import type { Page, RequestOut } from "@/lib/types";
import { useUrlState } from "@/lib/urlState";

function RequestsInner() {
  const { me } = useMe();
  const url = useUrlState();
  const direction = url.get("direction", "incoming") === "outgoing" ? "outgoing" : "incoming";
  const status = url.get("status", "open");
  const page = Number(url.get("page", "1")) || 1;
  const allowed = canUseRequests(me);
  const list = useApi<Page<RequestOut>>(allowed ? "/requests" : null, { direction, status, page, size: 25 });
  const openIncoming = useApi<Page<RequestOut>>(allowed ? "/requests" : null, { direction: "incoming", status: "open", size: 1 });
  const openOutgoing = useApi<Page<RequestOut>>(allowed ? "/requests" : null, { direction: "outgoing", status: "open", size: 1 });

  if (!allowed) return <Empty title="Requests are not available for your role" center />;

  return (
    <>
      <PageHeader title="Requests" sub={`Requests addressed to, or sent by, ${me.office.name} and the offices below it`} />
      <Tabs
        tabs={[
          { id: "incoming", label: "Incoming", count: openIncoming.data?.total },
          { id: "outgoing", label: "Outgoing", count: openOutgoing.data?.total },
        ]}
        active={direction}
        onChange={(d) => url.set({ direction: d === "incoming" ? null : d, page: null })}
        label="Request direction"
        idBase="requests"
      />
      <TabPanel idBase="requests" id={direction}>
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <Field label="Status">
              <Select value={status} onChange={(e) => url.set({ status: e.target.value === "open" ? null : e.target.value, page: null })} style={{ maxWidth: 240 }}>
                <option value="open">Open</option>
                <option value="answered">Answered</option>
                <option value="withdrawn">Withdrawn</option>
                <option value="all">All</option>
              </Select>
            </Field>
          </div>
          <Async state={list} loadingLabel="Loading requests">
            {(p) =>
              p.items.length === 0 ? (
                <Empty title={`No ${status === "all" ? "" : `${status} `}${direction} requests`} center />
              ) : (
                <>
                  {p.items.map((r) => (
                    <RequestCard
                      key={r.id}
                      r={r}
                      showCase
                      canAct={!me.read_only}
                      onChanged={() => {
                        list.reload();
                        openIncoming.reload();
                        openOutgoing.reload();
                      }}
                    />
                  ))}
                  <Pagination page={p.page} size={p.size} total={p.total} onPage={(n) => url.set({ page: n > 1 ? n : null })} noun="requests" />
                </>
              )
            }
          </Async>
        </div>
      </TabPanel>
    </>
  );
}

export default function RequestsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <RequestsInner />
    </Suspense>
  );
}
