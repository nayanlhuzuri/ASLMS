"use client";

/**
 * "Department mapping" under Administration (design portal-mapping, decisions 1 and 2; plan §4.1, §5.11; Annexure B):
 * counsel codes, keywords and name patterns, the watchlist and the scoring settings, one route per tab. A tab shows
 * with one of its functions; the API decides every read and write.
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, Loading, Tabs } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { mappingTabsFor } from "@/lib/routes";

export function MappingFrame({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "/admin/mapping";
  if (me.isPending) return <Loading />;
  const tabs = mappingTabsFor(me.data);
  return (
    <section className="stack" aria-label={T.mapping.title}>
      <h2>{T.mapping.title}</h2>
      {tabs.length > 0 ? (
        <Tabs
          label={T.mapping.tabs}
          items={tabs.map((t) => ({
            href: t.href,
            label: t.label,
            active: pathname === t.href || pathname.startsWith(t.href + "/"),
          }))}
        />
      ) : null}
      {tabs.length > 0 ? children : <EmptyState>{T.mapping.noTabs}</EmptyState>}
    </section>
  );
}

/** `/admin/mapping`: the first mapping tab the login may read. */
export function MappingIndex() {
  const me = useMe();
  const router = useRouter();
  const first = mappingTabsFor(me.data)[0];
  useEffect(() => {
    if (first) router.replace(first.href);
  }, [first, router]);
  if (me.isPending || first) return <Loading />;
  return null;
}
