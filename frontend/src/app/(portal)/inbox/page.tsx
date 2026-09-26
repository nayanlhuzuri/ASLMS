"use client";

import { Suspense } from "react";
import { DepartmentPicker } from "@/components/inbox/DepartmentPicker";
import { ClaimedPanel, RecommendedPanel, TransfersPanel, UnclaimedPanel } from "@/components/inbox/InboxPanels";
import { useMe, useOffices } from "@/components/shell/MeContext";
import { Icon } from "@/components/ui/Icon";
import { Notice, PageHeader } from "@/components/ui/Layout";
import { Empty, Loading } from "@/components/ui/States";
import { TabPanel, Tabs, type TabDef } from "@/components/ui/Tabs";
import { useApi } from "@/lib/hooks";
import { canUseDeptInbox, isOperator } from "@/lib/roles";
import type { CaseCard, Page, Recommendation, Transfer } from "@/lib/types";
import { useUrlState } from "@/lib/urlState";

function InboxInner() {
  const { me } = useMe();
  const { departments, byId } = useOffices();
  const url = useUrlState();
  const operator = isOperator(me);
  const deptInbox = canUseDeptInbox(me);
  const officeId = operator ? url.get("office") : undefined;
  const needsOffice = operator && !officeId;

  const tabs: TabDef[] = [];
  const tab = url.get("tab", deptInbox ? "recommended" : "unclaimed");
  const page = Number(url.get("page", "1")) || 1;

  const deptReady = deptInbox && !needsOffice;
  const counts = {
    recommended: useApi<Page<Recommendation>>(deptReady ? "/inbox/recommended" : null, { office_id: officeId, size: 1 }),
    claimed: useApi<Page<CaseCard>>(deptReady ? "/inbox/claimed" : null, { office_id: officeId, size: 1 }),
    unclaimed: useApi<Page<CaseCard>>("/inbox/unclaimed", { size: 1 }),
    transfers: useApi<Transfer[]>(deptReady ? "/inbox/transfers" : null, { office_id: officeId }),
  };
  const bump = () => Object.values(counts).forEach((c) => c.reload());
  if (deptInbox) {
    tabs.push({ id: "recommended", label: "Recommended", count: counts.recommended.data?.total });
    tabs.push({ id: "claimed", label: "Claimed", count: counts.claimed.data?.total });
  }
  tabs.push({ id: "unclaimed", label: "Unclaimed pool", count: counts.unclaimed.data?.total });
  if (deptInbox) {
    tabs.push({
      id: "transfers",
      label: "Transfers",
      count: counts.transfers.data ? counts.transfers.data.filter((t) => t.status === "requested").length : undefined,
    });
  }
  const activeTab = tabs.some((t) => t.id === tab) ? tab : tabs[0].id;
  const deptName = operator ? (officeId ? byId.get(officeId)?.name : undefined) : me.department?.name;
  const canAct = me.can_claim && !me.read_only && !needsOffice;

  const setTab = (id: string) => url.set({ tab: id, page: null, band: null, q: null });
  const setPage = (p: number) => url.set({ page: p > 1 ? p : null });

  return (
    <>
      <PageHeader
        title="Case Inbox"
        sub={
          deptInbox
            ? deptName
              ? `Cases recommended to ${deptName} from the daily cause lists`
              : "Choose a department to see its recommendations"
            : "Cases no department has claimed yet (read-only)"
        }
      />
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        {operator ? (
          <DepartmentPicker departments={departments} value={officeId ?? ""} onChange={(id) => url.set({ office: id, page: null })} />
        ) : null}
        <div style={{ flexGrow: 1 }} />
        <Notice>
          <Icon name="info" size={16} />
          No case is assigned automatically. A case becomes the department&apos;s only when claimed.
        </Notice>
      </div>
      <Tabs tabs={tabs} active={activeTab} onChange={setTab} label="Inbox" idBase="inbox" />
      <TabPanel idBase="inbox" id={activeTab}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {needsOffice && activeTab !== "unclaimed" ? (
            <Empty title="Choose a department" center>
              As central operator you act for one department at a time. Pick it above.
            </Empty>
          ) : activeTab === "recommended" ? (
            <RecommendedPanel
              officeId={officeId}
              canAct={canAct}
              onChanged={bump}
              departments={departments}
              band={url.get("band")}
              page={page}
              setBand={(b) => url.set({ band: b, page: null })}
              setPage={setPage}
            />
          ) : activeTab === "claimed" ? (
            <ClaimedPanel officeId={officeId} page={page} setPage={setPage} />
          ) : activeTab === "unclaimed" ? (
            <UnclaimedPanel
              officeId={officeId}
              canAct={canAct}
              onChanged={bump}
              q={url.get("q")}
              page={page}
              setQ={(q) => url.set({ q, page: null })}
              setPage={setPage}
            />
          ) : (
            <TransfersPanel officeId={officeId} canAct={canAct} onChanged={bump} />
          )}
        </div>
      </TabPanel>
    </>
  );
}

export default function InboxPage() {
  return (
    <Suspense fallback={<Loading />}>
      <InboxInner />
    </Suspense>
  );
}
