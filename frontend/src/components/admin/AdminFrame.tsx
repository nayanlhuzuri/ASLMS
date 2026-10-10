"use client";

/** Administration in tabs (Annexure B, "Department mapping"); each tab shows only with one of its functions. */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, Loading, Tabs } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { adminTabsFor } from "@/lib/routes";

export function AdminFrame({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "/admin";
  if (me.isPending) return <Loading />;
  const tabs = adminTabsFor(me.data);
  return (
    <div>
      <h1>{T.admin.title}</h1>
      {tabs.length > 0 ? (
        <Tabs
          label={T.admin.tabs}
          items={tabs.map((t) => ({
            href: t.href,
            label: t.label,
            active: pathname === t.href || pathname.startsWith(t.href + "/"),
          }))}
        />
      ) : null}
      {children}
    </div>
  );
}

/** `/admin`: the first tab the login may open. */
export function AdminIndex() {
  const me = useMe();
  const router = useRouter();
  const first = adminTabsFor(me.data)[0];
  useEffect(() => {
    if (first) router.replace(first.href);
  }, [first, router]);
  if (me.isPending || first) return <Loading />;
  return <EmptyState>{T.notFoundText}</EmptyState>;
}
