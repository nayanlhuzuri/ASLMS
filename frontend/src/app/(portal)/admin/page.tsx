"use client";

import { Suspense } from "react";
import { CodesTab } from "@/components/admin/CodesTab";
import { KeywordsTab } from "@/components/admin/KeywordsTab";
import { OfficesTab } from "@/components/admin/OfficesTab";
import { OpsTab } from "@/components/admin/OpsTab";
import { UsersTab } from "@/components/admin/UsersTab";
import { WatchlistTab } from "@/components/admin/WatchlistTab";
import { useMe } from "@/components/shell/MeContext";
import { Notice, PageHeader } from "@/components/ui/Layout";
import { Empty, Loading } from "@/components/ui/States";
import { TabPanel, Tabs, type TabDef } from "@/components/ui/Tabs";
import { canSeeAdmin, isOperator } from "@/lib/roles";
import { useUrlState } from "@/lib/urlState";

function AdminInner() {
  const { me } = useMe();
  const url = useUrlState();
  if (!canSeeAdmin(me)) {
    return <Empty title="Administration is not available for your role" center />;
  }
  const tabs: TabDef[] = [
    { id: "codes", label: "Standing counsel codes" },
    { id: "keywords", label: "Keywords & name patterns" },
    { id: "watchlist", label: "Watchlist" },
    { id: "users", label: "Users & roles" },
    { id: "offices", label: "Offices" },
  ];
  if (isOperator(me)) tabs.push({ id: "ops", label: "Operations" });
  const tab = url.get("tab", "codes");
  const active = tabs.some((t) => t.id === tab) ? tab : "codes";

  return (
    <>
      <PageHeader
        title={active === "codes" || active === "keywords" || active === "watchlist" ? "Department mapping" : "Administration"}
        sub={
          active === "codes" || active === "keywords" || active === "watchlist"
            ? "Codes and keywords used to recommend cases to departments"
            : isOperator(me)
              ? "State-wide administration"
              : `Administration of ${me.department?.name ?? me.office.name}`
        }
      />
      {!me.can_admin ? <Notice>Your role can view administration but not change it.</Notice> : null}
      <Tabs tabs={tabs} active={active} onChange={(t) => url.set({ tab: t === "codes" ? null : t })} label="Administration" idBase="admin" />
      <TabPanel idBase="admin" id={active}>
        {active === "codes" ? (
          <CodesTab me={me} />
        ) : active === "keywords" ? (
          <KeywordsTab me={me} />
        ) : active === "watchlist" ? (
          <WatchlistTab me={me} />
        ) : active === "users" ? (
          <UsersTab me={me} />
        ) : active === "offices" ? (
          <OfficesTab me={me} />
        ) : (
          <OpsTab />
        )}
      </TabPanel>
    </>
  );
}

export default function AdminPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AdminInner />
    </Suspense>
  );
}
