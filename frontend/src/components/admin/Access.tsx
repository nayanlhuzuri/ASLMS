"use client";

/**
 * User types and functions (design portal-shell, decision 15): the type × function matrix by module. Switching a
 * cell needs `access.manage_types` (the super admin); everyone else with `users.view` reads it.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { DataTable, ErrorBanner, Loading } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useLabels, useMe } from "@/lib/api/hooks";
import type { Permission, PermissionInfo } from "@/lib/api/types";
import { can } from "@/lib/can";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

type Matrix = Record<string, Record<string, boolean>>;

export function AccessMatrix() {
  const me = useMe();
  const labels = useLabels();
  const queryClient = useQueryClient();
  const matrix = useQuery({ queryKey: ["admin", "access", "types"], queryFn: () => api<Matrix>("/admin/access/types") });
  const permissions = useQuery({
    queryKey: ["admin", "permissions"],
    queryFn: () => api<PermissionInfo[]>("/admin/permissions"),
    staleTime: 10 * 60_000,
  });
  const action = useAction();
  const editable = can(me.data, "access.manage_types");

  if (matrix.isPending || permissions.isPending || labels.isPending) return <Loading />;
  const error = matrix.error ?? permissions.error ?? labels.error;
  if (error || !matrix.data || !permissions.data) return <ErrorBanner error={error} onRetry={() => matrix.refetch()} />;

  const types = (labels.data?.user_types ?? []).filter((t) => t.code in matrix.data);
  const modules = new Map<string, PermissionInfo[]>();
  for (const p of permissions.data.filter((x) => x.is_active)) {
    modules.set(p.module, [...(modules.get(p.module) ?? []), p]);
  }

  async function toggle(role: string, permission: Permission, enabled: boolean) {
    const out = await action.run(() =>
      api<Record<string, boolean>>(`/admin/access/types/${role}/${permission}`, { method: "PUT", body: { enabled } }),
    );
    if (out.ok) {
      queryClient.setQueryData<Matrix>(["admin", "access", "types"], (old) => ({ ...(old ?? {}), [role]: out.value }));
    }
  }

  return (
    <section className="stack" aria-label={T.access.title}>
      <h2>{T.access.title}</h2>
      {!editable ? <p className="muted">{T.access.readOnly}</p> : null}
      <ErrorBanner error={action.error} />
      {[...modules.entries()].map(([module, perms]) => (
        <DataTable
          key={module}
          caption={module}
          rows={perms}
          rowKey={(p) => p.code}
          columns={[
            {
              key: "function",
              header: T.access.function,
              primary: true,
              rowHeader: true,
              cell: (p) => (
                <>
                  {p.label} <span className="mono muted">{p.code}</span>
                </>
              ),
            },
            ...types.map((t) => ({
              key: t.code,
              header: <span title={t.description ?? t.label}>{t.label}</span>,
              label: t.label,
              cell: (p: PermissionInfo) => {
                const on = !!matrix.data[t.code]?.[p.code];
                const label = T.access.toggle(p.label, t.label);
                return editable && t.code !== "super_admin" && p.code !== "admin.tickets" ? (
                  <input
                    type="checkbox"
                    aria-label={label}
                    checked={on}
                    disabled={action.busy}
                    onChange={(e) => toggle(t.code, p.code, e.target.checked)}
                  />
                ) : (
                  <span aria-label={`${label}: ${on ? T.access.on : T.access.off}`} role="img">
                    {on ? "✓" : "–"}
                  </span>
                );
              },
            })),
          ]}
        />
      ))}
    </section>
  );
}
