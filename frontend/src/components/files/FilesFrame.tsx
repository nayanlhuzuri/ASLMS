"use client";

/**
 * "Files" (design portal-files-alerts, decisions 1, 12-14; plan §5.7, the eOffice view of custody-workflow decision 24):
 * up to four tabs — With me, My offices, Department files (only for a login tracking a department) and Sent — with
 * the one-time notice of a file just sent away above them. Showing a tab is convenience only: the API decides.
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, Loading, PageHeader, Tabs } from "@/components/ui";
import { FlashNotice } from "@/components/workflow/common";
import { useMe } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { filesTabsFor } from "@/lib/routes";

export function FilesFrame({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "/files";
  if (me.isPending) return <Loading />;
  const tabs = filesTabsFor(me.data);
  const allowed = pathname === "/files" || tabs.some((t) => pathname === t.href || pathname.startsWith(t.href + "/"));
  return (
    <div className="stack">
      <PageHeader title={T.files.title} />
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

/** `/files`: the first tab the login may open. */
export function FilesIndex() {
  const me = useMe();
  const router = useRouter();
  const first = filesTabsFor(me.data)[0];
  useEffect(() => {
    if (first) router.replace(first.href);
  }, [first, router]);
  if (me.isPending || first) return <Loading />;
  return <EmptyState>{T.notFoundText}</EmptyState>;
}
