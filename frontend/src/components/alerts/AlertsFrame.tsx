"use client";

/**
 * Alerts (design portal-files-alerts, decisions 1 and 13; plan §5.5; portal-ui-redesign, decision 8: its own menu
 * entry, the calendar moved to My calendar): tabs of one frame, the alert list (`/alerts`) and, with
 * `next_dates.review`, "Next dates to confirm" (`/alerts/next-dates`, design portal-next-dates, decision 1). The
 * "Alerts" tab is current only on `/alerts` itself. A login with no readable tab sees the neutral not-found text.
 */
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { EmptyState, Loading, PageHeader, Tabs } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { alertsTabsFor } from "@/lib/routes";

export function AlertsFrame({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "/alerts";
  if (me.isPending) return <Loading />;
  const tabs = alertsTabsFor(me.data);
  return (
    <div className="stack">
      <PageHeader title={T.alerts.title} />
      {tabs.length > 0 ? (
        <Tabs
          label={T.alerts.tabs}
          items={tabs.map((t) => ({
            href: t.href,
            label: t.label,
            active: t.href === "/alerts" ? pathname === "/alerts" : pathname === t.href || pathname.startsWith(t.href + "/"),
          }))}
        />
      ) : null}
      {tabs.length > 0 ? children : <EmptyState>{T.notFoundText}</EmptyState>}
    </div>
  );
}
