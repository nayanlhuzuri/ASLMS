"use client";

/** Designations (design portal-shell, decision 15): the list for everyone signed in; changes with `admin.designations`. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Badge, Button, DataTable, EmptyState, ErrorBanner, Loading, TextField } from "@/components/ui";
import { api } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import type { Designation } from "@/lib/api/types";
import { can } from "@/lib/can";
import { T } from "@/lib/messages";
import { useAction } from "@/lib/useAction";

export function Designations() {
  const me = useMe();
  const queryClient = useQueryClient();
  const manage = can(me.data, "admin.designations");
  const list = useQuery({
    queryKey: ["admin", "designations", manage ? "all" : "active"],
    queryFn: () => api<Designation[]>("/admin/designations", { query: { include_inactive: manage || undefined } }),
  });
  const [draft, setDraft] = useState({ code: "", name: "", order: "" });
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState({ name: "", order: "" });
  const action = useAction();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin", "designations"] });

  async function add(e: FormEvent) {
    e.preventDefault();
    const out = await action.run(() =>
      api("/admin/designations", {
        method: "POST",
        body: { code: draft.code.trim(), name: draft.name.trim(), sort_order: draft.order ? Number(draft.order) : null },
      }),
    );
    if (out.ok) {
      setDraft({ code: "", name: "", order: "" });
      await refresh();
    }
  }

  async function save(code: string) {
    const out = await action.run(() =>
      api(`/admin/designations/${encodeURIComponent(code)}`, {
        method: "PATCH",
        body: { name: edit.name.trim(), sort_order: edit.order ? Number(edit.order) : null },
      }),
    );
    if (out.ok) {
      setEditing(null);
      await refresh();
    }
  }

  async function setActive(code: string, active: boolean) {
    const out = await action.run(() =>
      api(`/admin/designations/${encodeURIComponent(code)}/${active ? "reactivate" : "deactivate"}`, { method: "POST" }),
    );
    if (out.ok) await refresh();
  }

  return (
    <section className="stack" aria-label={T.designations.title}>
      <h2>{T.designations.title}</h2>
      {manage ? (
        <form className="row" onSubmit={add}>
          <TextField label={T.designations.code} required value={draft.code} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
          <TextField label={T.designations.name} required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <TextField
            label={T.designations.order}
            type="number"
            value={draft.order}
            onChange={(e) => setDraft({ ...draft, order: e.target.value })}
          />
          <Button type="submit" busy={action.busy}>
            {T.designations.add}
          </Button>
        </form>
      ) : null}
      <ErrorBanner error={action.error} />
      {list.isPending ? <Loading /> : null}
      <ErrorBanner error={list.error} onRetry={() => list.refetch()} />
      {list.data ? (
        list.data.length === 0 ? (
          <EmptyState>{T.designations.empty}</EmptyState>
        ) : (
          <DataTable
            caption={T.designations.title}
            rows={list.data}
            rowKey={(d) => d.id}
            columns={[
              { key: "code", header: T.designations.code, cell: (d) => <span className="mono">{d.code}</span> },
              {
                key: "name",
                header: T.designations.name,
                primary: true,
                cell: (d) =>
                  editing === d.code ? (
                    <TextField label={T.designations.name} value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} />
                  ) : (
                    d.name
                  ),
              },
              {
                key: "order",
                header: T.designations.order,
                align: "right",
                cell: (d) =>
                  editing === d.code ? (
                    <TextField
                      label={T.designations.order}
                      type="number"
                      value={edit.order}
                      onChange={(e) => setEdit({ ...edit, order: e.target.value })}
                    />
                  ) : (
                    d.sort_order
                  ),
              },
              {
                key: "status",
                header: T.users.status,
                width: "var(--lead-w)",
                cell: (d) => (d.is_active ? <Badge tone="success">{T.active}</Badge> : <Badge>{T.inactive}</Badge>),
              },
              ...(manage
                ? [
                    {
                      key: "edit",
                      header: <span className="visually-hidden">{T.edit}</span>,
                      label: T.edit,
                      cell: (d: (typeof list.data)[number]) => (
                        <div className="actions">
                          {editing === d.code ? (
                            <>
                              <Button variant="link" busy={action.busy} onClick={() => save(d.code)}>
                                {T.save}
                              </Button>
                              <Button variant="link" onClick={() => setEditing(null)}>
                                {T.cancel}
                              </Button>
                            </>
                          ) : (
                            <Button
                              variant="link"
                              onClick={() => {
                                setEdit({ name: d.name, order: String(d.sort_order) });
                                setEditing(d.code);
                              }}
                            >
                              {T.edit}
                            </Button>
                          )}
                          <Button variant="link" busy={action.busy} onClick={() => setActive(d.code, !d.is_active)}>
                            {d.is_active ? T.offices.deactivate : T.offices.reactivate}
                          </Button>
                        </div>
                      ),
                    },
                  ]
                : []),
            ]}
          />
        )
      ) : null}
    </section>
  );
}
