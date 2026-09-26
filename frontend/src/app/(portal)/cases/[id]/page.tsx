"use client";

import { useParams } from "next/navigation";
import { Suspense } from "react";
import { caseNumber, ownerName } from "@/components/case/CaseBits";
import { ActionRail } from "@/components/case/detail/ActionRail";
import { CaseHeader } from "@/components/case/detail/CaseHeader";
import s from "@/components/case/detail/detail.module.css";
import { DocumentsTab } from "@/components/case/detail/DocumentsTab";
import { OverviewTab } from "@/components/case/detail/OverviewTab";
import { AssistantPanel, NotesPanel } from "@/components/case/detail/PhasePanels";
import { HearingsTab, LinksTab, ListingsCard, OrdersTab, OwnershipTab, SignalsTab, TimelineTab } from "@/components/case/detail/SimpleTabs";
import { useMe } from "@/components/shell/MeContext";
import { Card, CardHead, KV, Notice } from "@/components/ui/Layout";
import { HearingPill } from "@/components/ui/Pill";
import { ErrorState, Loading } from "@/components/ui/States";
import { TabPanel, Tabs, type TabDef } from "@/components/ui/Tabs";
import { fmtDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { CaseCard, CaseDetail } from "@/lib/types";
import { useUrlState } from "@/lib/urlState";

const TABS: TabDef[] = [
  { id: "overview", label: "Overview" },
  { id: "hearings", label: "Hearings" },
  { id: "orders", label: "Orders" },
  { id: "documents", label: "Documents" },
  { id: "links", label: "Linked cases" },
  { id: "timeline", label: "Timeline" },
  { id: "ownership", label: "Ownership history" },
  { id: "signals", label: "Signals" },
  { id: "notes", label: "Notes & custody" },
  { id: "assistant", label: "Case Assistant" },
];

function isDetail(c: CaseCard | CaseDetail): c is CaseDetail {
  return c.in_scope === true && "parties" in c;
}

function TrackingView({ c }: { c: CaseCard }) {
  const owner = ownerName(c);
  return (
    <>
      <Notice>
        This case is outside your department&apos;s access, so only its tracking card is shown: status, next hearing, owner and cause-list appearances.
      </Notice>
      <div className={s.columns}>
        <div className={s.main}>
          <Card>
            <CardHead title="Next hearing" caption />
            {c.next_hearing_date ? (
              <div className={s.bigDateRow}>
                <div className={s.bigDate}>{fmtDate(c.next_hearing_date)}</div>
                <HearingPill date={c.next_hearing_date} />
              </div>
            ) : (
              <p className="muted">No next date known.</p>
            )}
            <KV
              items={[
                { label: "Purpose", value: c.next_purpose ?? "-" },
                { label: "Last hearing", value: fmtDate(c.last_hearing_date) },
                { label: "Court", value: c.court ?? "-" },
              ]}
            />
          </Card>
          <ListingsCard caseId={c.id} />
          <TimelineTab caseId={c.id} trackingOnly />
        </div>
        <div className={s.side}>
          <Card>
            <CardHead title="Ownership" caption />
            <KV
              items={[
                { label: "Held by", value: owner ?? "Not claimed by any department" },
                { label: "Watching", value: c.owners?.watchers?.length ? c.owners.watchers.map((w) => w.name).join(", ") : "None" },
              ]}
            />
          </Card>
        </div>
      </div>
    </>
  );
}

function CaseInner() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { me } = useMe();
  const url = useUrlState();
  const state = useApi<CaseCard | CaseDetail>(`/cases/${id}`);
  const tab = url.get("tab", "overview");
  const active = TABS.some((t) => t.id === tab) ? tab : "overview";

  if (state.error) return <ErrorState message={state.error} onRetry={state.reload} />;
  if (!state.data) return <Loading label="Loading the case" />;
  const c = state.data;
  const rail = <ActionRail me={me} c={c} onChanged={state.reload} />;

  if (!isDetail(c)) {
    return (
      <>
        <title>{caseNumber(c)}</title>
        <CaseHeader c={c} rail={rail} />
        <TrackingView c={c} />
      </>
    );
  }

  const setTab = (t: string) => url.set({ tab: t === "overview" ? null : t });

  return (
    <>
      <title>{caseNumber(c)}</title>
      <CaseHeader c={c} rail={rail} />
      <Tabs tabs={TABS} active={active} onChange={setTab} label="Case sections" idBase="case" />
      <TabPanel idBase="case" id={active}>
        {active === "overview" ? (
          <OverviewTab c={c} me={me} onChanged={state.reload} onOpenTab={setTab} />
        ) : active === "hearings" ? (
          <HearingsTab caseId={c.id} />
        ) : active === "orders" ? (
          <OrdersTab caseId={c.id} />
        ) : active === "documents" ? (
          <DocumentsTab caseId={c.id} canUpload={!me.read_only} />
        ) : active === "links" ? (
          <LinksTab c={c} />
        ) : active === "timeline" ? (
          <TimelineTab caseId={c.id} />
        ) : active === "ownership" ? (
          <OwnershipTab caseId={c.id} />
        ) : active === "signals" ? (
          <SignalsTab caseId={c.id} />
        ) : active === "notes" ? (
          <NotesPanel />
        ) : (
          <AssistantPanel />
        )}
      </TabPanel>
    </>
  );
}

export default function CasePage() {
  return (
    <Suspense fallback={<Loading />}>
      <CaseInner />
    </Suspense>
  );
}
