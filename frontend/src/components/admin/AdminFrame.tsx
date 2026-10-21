"use client";

/**
 * Administration (Annexure B, "Department mapping") on the Settings template (design portal-ui-redesign, decision
 * 26): the setting groups (users, access, offices, designations, Department mapping, tickets) as a sub-menu on the
 * left on laptops and a select on phones, one group at a time beside it. Each group shows only with one of its
 * functions; the API decides every read and write.
 */
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { EmptyState, Loading, PageHeader, SettingsLayout } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";
import { T } from "@/lib/messages";
import { adminTabsFor } from "@/lib/routes";

export function AdminFrame({ children }: { children: ReactNode }) {
  const me = useMe();
  const pathname = usePathname() ?? "/admin";
  if (me.isPending) return <Loading />;
  const tabs = adminTabsFor(me.data);
  return (
    <div className="stack">
      <PageHeader title={T.admin.title} subtitle={T.admin.subtitle} />
      {tabs.length > 0 ? (
        <SettingsLayout
          label={T.admin.tabs}
          selectLabel={T.admin.group}
          items={tabs.map((t) => ({
            key: t.key,
            href: t.href,
            label: t.label,
            active: pathname === t.href || pathname.startsWith(t.href + "/"),
          }))}
        >
          {children}
        </SettingsLayout>
      ) : (
        children
      )}
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
