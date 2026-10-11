"use client";

/**
 * "Data collection" in four tabs (design data-load-console, decision 19): the load console, data health, the queue
 * and call log, and duplicates. The entry and its tabs show for `admin.data_load` or a health reader; every button
 * shows by its own function. Showing is convenience only: the API decides every figure and action.
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, Loading, Tabs } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { dataTabsFor } from "@/lib/routes";

export function DataFrame({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "/data/load";
  if (me.isPending) return <Loading />;
  const tabs = dataTabsFor(me.data);
  return (
    <div>
      <h1>{T.data.title}</h1>
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

/** `/data`: the first tab the login may open. */
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
