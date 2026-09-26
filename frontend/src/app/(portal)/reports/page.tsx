"use client";

import { Suspense, useState, type FormEvent } from "react";
import { DataHealthView } from "@/components/reports/DataHealthView";
import { ReportView } from "@/components/reports/ReportView";
import { useMe } from "@/components/shell/MeContext";
import { Button } from "@/components/ui/Button";
import { Field, TextInput } from "@/components/ui/Field";
import { PageHeader } from "@/components/ui/Layout";
import { Loading } from "@/components/ui/States";
import { TabPanel, Tabs, type TabDef } from "@/components/ui/Tabs";
import { addDays, todayIST } from "@/lib/format";
import { canSeeDataHealth } from "@/lib/roles";
import { useUrlState } from "@/lib/urlState";

function HearingsDisposals() {
  const url = useUrlState();
  const end = url.get("end") || todayIST();
  const start = url.get("start") || addDays(end, -30);
  const [ds, setDs] = useState(start);
  const [de, setDe] = useState(end);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    url.set({ start: ds, end: de });
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <form onSubmit={submit} className="no-print" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <Field label="From">
          <TextInput type="date" required value={ds} max={de} onChange={(e) => setDs(e.target.value)} />
        </Field>
        <Field label="To">
          <TextInput type="date" required value={de} min={ds} onChange={(e) => setDe(e.target.value)} />
        </Field>
        <Button type="submit">Show</Button>
      </form>
      <ReportView path="/reports/hearings-disposals" query={{ start, end }} empty="No hearings or disposals in this period" />
    </div>
  );
}

function ReportsInner() {
  const { me } = useMe();
  const url = useUrlState();
  const tabs: TabDef[] = [
    { id: "pending-by-department", label: "Pending by department" },
    { id: "pending-by-court", label: "Pending by court" },
    { id: "open-actions-by-office", label: "Open actions by office" },
    { id: "hearings-disposals", label: "Hearings and disposals" },
  ];
  if (canSeeDataHealth(me)) tabs.push({ id: "data-health", label: "Data collection health" });
  const tab = url.get("tab", tabs[0].id);
  const active = tabs.some((t) => t.id === tab) ? tab : tabs[0].id;

  return (
    <>
      <PageHeader title="Reports" sub="Figures cover the cases within your access. Export to Excel or CSV, or print." />
      <Tabs tabs={tabs} active={active} onChange={(t) => url.set({ tab: t, start: null, end: null })} label="Reports" idBase="reports" />
      <TabPanel idBase="reports" id={active}>
        {active === "hearings-disposals" ? (
          <HearingsDisposals />
        ) : active === "data-health" ? (
          <DataHealthView />
        ) : (
          <ReportView key={active} path={`/reports/${active}`} empty="Nothing to report" />
        )}
      </TabPanel>
    </>
  );
}

export default function ReportsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ReportsInner />
    </Suspense>
  );
}
