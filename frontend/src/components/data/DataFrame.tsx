"use client";

/**
 * "Data Collection" (design data-collection-redesign, decisions 1, 2 and 7): the tabs Overview, Collect Now and
 * Automatic Collection, then, until round 2, the old Health, Queue and Calls and Duplicates. Each tab shows by its own
 * functions and every button by its own function; showing is convenience only: the API decides every figure and
 * action. The frame is a `stack` like `AdminFrame`, so the page keeps its gutter whatever the content (decision 7).
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, Loading, PageHeader, Tabs } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { dataTabsFor } from "@/lib/routes";

export function DataFrame({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "/data/overview";
  if (me.isPending) return <Loading />;
  const tabs = dataTabsFor(me.data);
  return (
    <div className="stack">
      <PageHeader title={T.data.title} />
      {tabs.length > 0 ? (
        <Tabs
          label={T.data.tabs}
          items={tabs.map((t) => ({
            href: t.href,
            label: t.label,
            active: pathname === t.href || pathname.startsWith(t.href + "/"),
          }))}
        />
      ) : null}
      {tabs.length > 0 ? children : <EmptyState>{T.notFoundText}</EmptyState>}
    </div>
  );
}

/** `/data`: Overview, or the first tab the login may open. */
export function DataIndex() {
  const me = useMe();
  const router = useRouter();
  const first = dataTabsFor(me.data)[0];
  useEffect(() => {
    if (first) router.replace(first.href);
  }, [first, router]);
  if (me.isPending || first) return <Loading />;
  return <EmptyState>{T.notFoundText}</EmptyState>;
}
