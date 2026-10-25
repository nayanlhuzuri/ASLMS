"use client";

/**
 * "Cases", the Cases list (design case-workspace-admin, decision 17; it replaces Files of portal-files-alerts): three
 * tabs — Cases with me, Sent by me and Pending action (only for a login tracking a department) — with the one-time
 * notice of a case just sent away above them. Showing a tab is convenience only: the API decides. The internal names
 * (`components/files/*`) stay (decision 2).
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, Loading, PageHeader, Tabs } from "@/components/ui";
import { FlashNotice } from "@/components/workflow/common";
import { useMe } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { casesTabsFor } from "@/lib/routes";

export function CasesFrame({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "/cases";
  if (me.isPending) return <Loading />;
  const tabs = casesTabsFor(me.data);
  const allowed = tabs.some((t) => pathname === t.href || pathname.startsWith(t.href + "/"));
  return (
    <div className="stack">
      <PageHeader title={T.files.title} subtitle={T.files.subtitle} />
      <FlashNotice />
      {tabs.length > 0 ? (
        <Tabs
          label={T.files.tabs}
          items={tabs.map((t) => ({
            href: t.href,
            label: t.label,
            active: pathname === t.href || pathname.startsWith(t.href + "/"),
          }))}
        />
      ) : null}
      {tabs.length > 0 && allowed ? children : <EmptyState>{T.notFoundText}</EmptyState>}
    </div>
  );
}

/** `/cases`: the first tab the login may open; with none, Search (which `/cases` showed until now). */
export function CasesIndex() {
  const me = useMe();
  const router = useRouter();
  const first = casesTabsFor(me.data)[0];
  const target = me.isPending ? null : (first?.href ?? "/search");
  useEffect(() => {
    if (target) router.replace(target);
  }, [target, router]);
  return <Loading />;
}
